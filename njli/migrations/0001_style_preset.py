"""Add ``persona.style_preset`` (default ``plain``) to workspaces created before it existed."""

DESCRIPTION = "add persona.style_preset (default 'plain')"
TOUCHES_POLICY = False
FILES = ["config/njli.json"]


def plan(ctx):
    cfg = ctx.config_raw()
    persona = cfg.get("persona")
    if isinstance(persona, dict) and "style_preset" not in persona:
        return ["config/njli.json: persona.style_preset = 'plain'"]
    return []


def apply(ctx):
    cfg = ctx.config_raw()
    persona = cfg.get("persona")
    if isinstance(persona, dict) and "style_preset" not in persona:
        persona["style_preset"] = "plain"
        ctx.save_config(cfg)
