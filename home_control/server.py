import os
import asyncio
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web

TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
REST = "http://supervisor/core/api"
WS = "ws://supervisor/core/websocket"
WWW = Path("/www")

registry_cache = None
registry_lock = asyncio.Lock()


async def rest_get(session, path):
    async with session.get(
        REST + path,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    ) as response:
        response.raise_for_status()
        return await response.json()


async def websocket_registries(session):
    results = {}
    print("HOME CONTROL: opening registry websocket", flush=True)

    async with session.ws_connect(WS) as ws:
        hello = await asyncio.wait_for(
            ws.receive_json(),
            timeout=10
        )
        print(
            "HOME CONTROL: websocket greeting:",
            hello.get("type"),
            flush=True
        )

        if hello.get("type") != "auth_required":
            raise RuntimeError(
                f"Unexpected WebSocket greeting: {hello}"
            )

        await ws.send_json({
            "type": "auth",
            "access_token": TOKEN,
        })

        auth = await asyncio.wait_for(
            ws.receive_json(),
            timeout=10
        )
        print(
            "HOME CONTROL: websocket auth:",
            auth.get("type"),
            flush=True
        )

        if auth.get("type") != "auth_ok":
            raise RuntimeError(
                f"WebSocket authentication failed: {auth}"
            )

        commands = [
            ("areas", "config/area_registry/list"),
            ("devices", "config/device_registry/list"),
            ("entities", "config/entity_registry/list"),
        ]

        for command_id, (key, command) in enumerate(commands, start=1):
            print(
                "HOME CONTROL: requesting",
                command,
                flush=True
            )

            await ws.send_json({
                "id": command_id,
                "type": command,
            })

            while True:
                message = await asyncio.wait_for(
                    ws.receive_json(),
                    timeout=10
                )

                if message.get("id") != command_id:
                    continue

                if not message.get("success"):
                    raise RuntimeError(
                        f"{command} failed: {message}"
                    )

                results[key] = message.get("result", [])
                print(
                    "HOME CONTROL:",
                    command,
                    "returned",
                    len(results[key]),
                    "records",
                    flush=True
                )
                break

    return results


async def get_registries(session):
    global registry_cache

    async with registry_lock:
        if registry_cache is None:
            registry_cache = await websocket_registries(session)

    return registry_cache

async def bootstrap(request):
    print("HOME CONTROL: bootstrap requested", flush=True)

    try:
        timeout = ClientTimeout(total=25)

        async with ClientSession(timeout=timeout) as session:
            config, states = await asyncio.gather(
                rest_get(session, "/config"),
                rest_get(session, "/states"),
            )

            registries = await get_registries(session)

        return web.json_response({
            "config": config,
            "states": states,
            "areas": registries["areas"],
            "devices": registries["devices"],
            "entities": registries["entities"],
        })

    except Exception as error:
        print(
            "HOME CONTROL: BOOTSTRAP ERROR:",
            repr(error),
            flush=True,
        )

        return web.json_response(
            {
                "error": type(error).__name__,
                "message": str(error).split(" headers=")[0],
            },
            status=502,
        )



async def states(request):
    try:
        async with ClientSession(
            timeout=ClientTimeout(total=15)
        ) as session:
            data = await rest_get(session, "/states")

        return web.json_response(data)

    except Exception as error:
        return web.json_response(
            {
                "error": type(error).__name__,
                "message": str(error).split(" headers=")[0],
            },
            status=502,
        )



async def call_service(request):
    try:
        data = await request.json()

        domain = data.get("domain")
        service = data.get("service")
        entity_id = data.get("entity_id")

        allowed_services = {
            "light": {
                "turn_on",
                "turn_off",
            },
            "media_player": {
                "media_play_pause",
                "volume_mute",
                "volume_set",
            },
            "button": {
                "press",
            },
        }

        if domain not in allowed_services:
            return web.json_response(
                {"error": "Unsupported domain"},
                status=403,
            )

        if service not in allowed_services[domain]:
            return web.json_response(
                {"error": "Unsupported service"},
                status=403,
            )

        if not entity_id or not entity_id.startswith(domain + "."):
            return web.json_response(
                {"error": "Invalid entity"},
                status=400,
            )

        if domain == "button":
            allowed_snapshot_buttons = {
                "button.front_door_take_snapshot",
                "button.side_porch_take_snapshot",
                "button.main_floor_take_snapshot",
                "button.garage_take_snapshot",
            }

            if entity_id not in allowed_snapshot_buttons:
                return web.json_response(
                    {"error": "Unsupported button"},
                    status=403,
                )

        service_data = {
            "entity_id": entity_id,
        }

        brightness_pct = data.get("brightness_pct")

        if (
            service == "turn_on"
            and brightness_pct is not None
        ):
            try:
                brightness_pct = int(brightness_pct)
            except (TypeError, ValueError):
                return web.json_response(
                    {"error": "Invalid brightness"},
                    status=400,
                )

            brightness_pct = max(
                1,
                min(100, brightness_pct)
            )

            service_data["brightness_pct"] = brightness_pct

        if domain == "media_player":
            if service == "volume_mute":
                service_data["is_volume_muted"] = bool(
                    data.get("is_volume_muted")
                )

            if service == "volume_set":
                try:
                    volume_level = float(
                        data.get("volume_level")
                    )
                except (TypeError, ValueError):
                    return web.json_response(
                        {"error": "Invalid volume"},
                        status=400,
                    )

                service_data["volume_level"] = max(
                    0.0,
                    min(1.0, volume_level)
                )

        async with ClientSession(
            timeout=ClientTimeout(total=15)
        ) as session:
            async with session.post(
                f"{REST}/services/{domain}/{service}",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Content-Type": "application/json",
                },
                json=service_data,
            ) as response:
                response.raise_for_status()
                result = await response.json()

        print(
            "HOME CONTROL: service call",
            domain,
            service,
            entity_id,
            flush=True,
        )

        return web.json_response({
            "ok": True,
            "result": result,
        })

    except Exception as error:
        print(
            "HOME CONTROL: SERVICE ERROR:",
            repr(error),
            flush=True,
        )

        return web.json_response(
            {
                "error": type(error).__name__,
                "message": str(error).split(" headers=")[0],
            },
            status=502,
        )



async def camera_image(request):
    entity_id = request.match_info.get("entity_id", "")

    if not entity_id.startswith("camera."):
        return web.json_response(
            {"error": "Invalid camera entity"},
            status=400,
        )

    try:
        async with ClientSession(
            timeout=ClientTimeout(total=20)
        ) as session:
            async with session.get(
                f"{REST}/camera_proxy/{entity_id}",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                },
            ) as response:
                response.raise_for_status()

                body = await response.read()

                content_type = response.headers.get(
                    "Content-Type",
                    "image/jpeg"
                )

        return web.Response(
            body=body,
            content_type=content_type.split(";")[0],
            headers={
                "Cache-Control": "no-store"
            },
        )

    except Exception as error:
        print(
            "HOME CONTROL: CAMERA IMAGE ERROR:",
            entity_id,
            repr(error),
            flush=True,
        )

        return web.json_response(
            {
                "error": type(error).__name__,
                "message": str(error).split(" headers=")[0],
            },
            status=502,
        )



async def camera_signals(request):
    try:
        async with ClientSession(
            timeout=ClientTimeout(total=25)
        ) as session:
            states = await rest_get(
                session,
                "/states"
            )

            registries = await get_registries(
                session
            )

        areas = registries["areas"]
        devices = registries["devices"]
        entities = registries["entities"]

        state_map = {
            item["entity_id"]: item
            for item in states
        }

        device_map = {
            item["id"]: item
            for item in devices
        }

        area_map = {
            item["area_id"]: item
            for item in areas
        }

        ring_device_ids = {
            entity.get("device_id")
            for entity in entities
            if (
                entity.get("platform") == "ring"
                and entity.get("device_id")
            )
        }

        allowed_domains = {
            "camera",
            "binary_sensor",
            "sensor",
            "event",
            "button",
        }

        results = []

        for entity in entities:
            entity_id = entity.get(
                "entity_id",
                ""
            )

            if "." not in entity_id:
                continue

            domain = entity_id.split(
                ".",
                1
            )[0]

            if domain not in allowed_domains:
                continue

            is_ring_platform = (
                entity.get("platform") == "ring"
            )

            is_ring_device = (
                entity.get("device_id")
                in ring_device_ids
            )

            if not (
                is_ring_platform
                or is_ring_device
            ):
                continue

            state = state_map.get(
                entity_id,
                {}
            )

            device = device_map.get(
                entity.get("device_id"),
                {}
            )

            area_id = (
                entity.get("area_id")
                or device.get("area_id")
            )

            area = area_map.get(
                area_id,
                {}
            )

            attrs = state.get(
                "attributes",
                {}
            )

            useful_attributes = {}

            if (
                domain == "camera"
                and entity_id.endswith(
                    "_last_recording"
                )
            ):
                useful_attributes = dict(attrs)

            else:
                for key in [
                    "device_class",
                    "friendly_name",
                    "event_types",
                    "event_type",
                    "attribution",
                ]:
                    if key in attrs:
                        useful_attributes[key] = attrs[key]

            results.append({
                "entity_id": entity_id,
                "domain": domain,
                "platform": entity.get("platform"),
                "state": state.get("state"),
                "last_changed": state.get("last_changed"),
                "last_updated": state.get("last_updated"),
                "area": area.get("name"),
                "device_name":
                    device.get("name_by_user")
                    or device.get("name"),
                "attributes": useful_attributes,
            })

        results.sort(
            key=lambda item: (
                item.get("area") or "",
                item.get("domain") or "",
                item.get("entity_id") or "",
            )
        )

        return web.json_response({
            "count": len(results),
            "signals": results,
        })

    except Exception as error:
        print(
            "HOME CONTROL: CAMERA SIGNAL ERROR:",
            repr(error),
            flush=True,
        )

        return web.json_response(
            {
                "error": type(error).__name__,
                "message": str(error).split(" headers=")[0],
            },
            status=502,
        )



async def raw_entity_state(request):
    entity_id = request.match_info.get("entity_id", "")

    if not entity_id:
        return web.json_response(
            {"error": "Missing entity_id"},
            status=400,
        )

    try:
        async with ClientSession(
            timeout=ClientTimeout(total=15)
        ) as session:
            state = await rest_get(
                session,
                f"/states/{entity_id}",
            )

        return web.json_response(state)

    except Exception as error:
        print(
            "HOME CONTROL: RAW STATE ERROR:",
            entity_id,
            repr(error),
            flush=True,
        )

        return web.json_response(
            {
                "error": type(error).__name__,
                "message": str(error).split(" headers=")[0],
            },
            status=502,
        )



async def ring_mqtt_diagnostics(request):
    try:
        async with ClientSession(
            timeout=ClientTimeout(total=20)
        ) as session:
            states = await rest_get(
                session,
                "/states",
            )

        camera_terms = (
            "front_door",
            "front door",
            "side_porch",
            "side porch",
            "garage",
            "main_floor",
            "main floor",
        )

        ring_terms = (
            "ring",
            "mqtt",
        )

        results = []

        for state in states:
            entity_id = state.get(
                "entity_id",
                ""
            )

            attrs = state.get(
                "attributes",
                {}
            )

            friendly_name = str(
                attrs.get(
                    "friendly_name",
                    ""
                )
            )

            text = (
                entity_id +
                " " +
                friendly_name
            ).lower()

            matches_camera = any(
                term in text
                for term in camera_terms
            )

            matches_ring = any(
                term in text
                for term in ring_terms
            )

            if not matches_camera:
                continue

            # Keep camera-related entities even when
            # "ring" or "mqtt" is not in the entity name,
            # because Ring-MQTT entities often use only
            # the device/location name.
            domain = (
                entity_id.split(".", 1)[0]
                if "." in entity_id
                else ""
            )

            interesting_domains = {
                "camera",
                "sensor",
                "binary_sensor",
                "event",
                "switch",
                "button",
                "select",
                "number",
                "text",
            }

            if (
                not matches_ring
                and domain not in interesting_domains
            ):
                continue

            results.append({
                "entity_id": entity_id,
                "domain": domain,
                "state": state.get("state"),
                "friendly_name": friendly_name,
                "attributes": attrs,
            })

        results.sort(
            key=lambda item: (
                item.get("friendly_name") or "",
                item.get("entity_id") or "",
            )
        )

        return web.json_response({
            "count": len(results),
            "entities": results,
        })

    except Exception as error:
        print(
            "HOME CONTROL: RING MQTT DIAGNOSTIC ERROR:",
            type(error).__name__,
            flush=True,
        )

        return web.json_response(
            {
                "error": type(error).__name__,
                "message": "Ring MQTT diagnostic request failed",
            },
            status=502,
        )


async def index(request):
    return web.FileResponse(WWW / "index.html")


async def health(request):
    return web.json_response({
        "ok": True,
        "token_present": bool(TOKEN),
        "version": "0.2.0",
    })


app = web.Application()

app.router.add_get("/", index)
app.router.add_get("/api/bootstrap", bootstrap)
app.router.add_get("/api/states", states)
app.router.add_get("/api/health", health)
app.router.add_get("/api/ring-mqtt-diagnostics", ring_mqtt_diagnostics)
app.router.add_get("/api/entity/{entity_id}", raw_entity_state)
app.router.add_get("/api/camera-signals", camera_signals)
app.router.add_get("/api/camera/{entity_id}", camera_image)
app.router.add_post("/api/service", call_service)

web.run_app(
    app,
    host="0.0.0.0",
    port=8099,
    print=None,
)
