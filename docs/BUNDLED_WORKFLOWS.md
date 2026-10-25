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

The optional desktop workflow installer copies these files into:

```
<selected ComfyUI installation>/user/default/workflows/
```

This is the folder shown in the regular ComfyUI workflow browser. Use the same
location when offering installation for an existing installation or after a fresh
ComfyUI setup. The shorter `user/workflows` path is incorrect for this setup.
Do not copy them into the controller's own settings/preset folders. Preserve
existing workflows and ask before replacing matching filenames.

## Using the desktop installer

Click **Install bundled workflows** beside Settings in the native desktop app.
The same dialog is offered after choosing an existing ComfyUI installation or
completing fresh Comfy CLI setup. Cancelling does not install anything. The app
does not repeatedly prompt at startup; the permanent button remains available.

Select the workflows (all three start selected), review the displayed destination,
and click **Install selected**. Existing files are skipped by default and identical
files are reported as up to date. To replace a different existing workflow, select
**Replace existing workflows** and confirm the listed filenames. A file changed
since review is preserved; refresh and review it again before replacing it.

Results list installed, skipped and failed files. **Refresh** checks the current
folder again; **Open ComfyUI WebUI** uses the configured ComfyUI endpoint (the
regular backend address from Mobile WebUI settings, not the controller's Phone
page). Start ComfyUI first if needed. No browser is opened automatically.

File checks/copying run in a bounded isolated worker. The installer uses temporary
files, no-follow directory/file checks and atomic writes. Unknown filenames,
symlinks and changed installation/directory identities cannot redirect a copy.
Partial failures preserve successful copies and report individual errors. A timeout
requires a refresh and never automatically resubmits installation.

## User-facing setup notice

**One-time setup in ComfyUI required**

Open the regular ComfyUI WebUI and load each bundled workflow. Use ComfyUI Manager
to install its missing custom nodes, then restart ComfyUI when prompted. Afterwards,
return to ComfyUI Control. Any model weights or input images referenced by a
workflow also need to be available in the ComfyUI installation.

Show this notice for both existing and fresh installations. Copying workflow JSONs
must not silently install custom nodes, model weights or execute the workflows.
