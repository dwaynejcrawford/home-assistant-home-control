# home-assistant-home-control
Custom Home Assistant control interface

## Publish without `git push`

Use `scripts/publish_to_github.py` when terminal Git credentials are not
working. It validates the add-on, builds a local repository archive, and can
publish the current source files to GitHub with one Git Data API commit.

Dry run:

```bash
python3 scripts/publish_to_github.py
```

Publish:

```bash
export GITHUB_TOKEN="ghp_..."
python3 scripts/publish_to_github.py --publish
```

Optional environment variables:

- `HA_REPOSITORY`: defaults to `dwaynejcrawford/home-assistant-home-control`
- `GITHUB_BRANCH`: defaults to `main`
- `NODE_BINARY`: optional path to Node.js for JavaScript syntax validation

After publishing, refresh the add-on repository in Home Assistant and rebuild
or update the Home Control add-on.
