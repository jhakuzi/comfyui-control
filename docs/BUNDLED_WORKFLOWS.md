# Bundled ComfyUI workflows

These original saved-editor workflows are included in
`comfyui_control/assets/workflows/`:

- `VeryComfy.json`
- `OfficialComfy-SeedVR_Upscaler.json`
- `VeryComfy_Qwen21_Turbo_EDIT_ONLY.json`

They were copied unchanged from the user's ComfyUI saved workflows on
2026-10-25. Their models, node choices, links, subgraphs and editor state are
preserved. They are included in Python wheels, app ZIPs and source RPMs. Model
weights, custom-node code and referenced input images are not bundled.

## Installation target

The desktop workflow installer must copy these files into:

```
<selected ComfyUI installation>/user/default/workflows/
```

This is the folder shown in the regular ComfyUI workflow browser. Use the same
location when offering installation for an existing installation or after a fresh
ComfyUI setup. The shorter `user/workflows` path is incorrect for this setup.
Do not copy them into the controller's own settings/preset folders. Preserve
existing workflows and ask before replacing matching filenames.

This commit adds the bundled files and package inclusion only. The optional
desktop installation offer and Open ComfyUI WebUI button are still to be implemented.

## User-facing setup notice

**One-time setup in ComfyUI required**

Open the regular ComfyUI WebUI and load each bundled workflow. Use ComfyUI Manager
to install its missing custom nodes, then restart ComfyUI when prompted. Afterwards,
return to ComfyUI Control. Any model weights or input images referenced by a
workflow also need to be available in the ComfyUI installation.

Show this notice for both existing and fresh installations. Copying workflow JSONs
must not silently install custom nodes, model weights or execute the workflows.
