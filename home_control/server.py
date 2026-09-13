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
            {"error": repr(error)},
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
            {"error": repr(error)},
            status=502,
        )



async def call_service(request):
    try:
        data = await request.json()

        domain = data.get("domain")
        service = data.get("service")
        entity_id = data.get("entity_id")

        if domain != "light":
            return web.json_response(
                {"error": "Only light controls are enabled"},
                status=403,
            )

        if service not in {"turn_on", "turn_off"}:
            return web.json_response(
                {"error": "Unsupported light service"},
                status=403,
            )

        if not entity_id or not entity_id.startswith("light."):
            return web.json_response(
                {"error": "Invalid light entity"},
                status=400,
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
                json={
                    "entity_id": entity_id,
                },
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
            {"error": repr(error)},
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
app.router.add_post("/api/service", call_service)

web.run_app(
    app,
    host="0.0.0.0",
    port=8099,
    print=None,
)
