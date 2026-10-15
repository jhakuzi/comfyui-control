# Mobile WebUI — preliminary testing

This feature is integrated into the desktop app on **`testing/mobile-webui`**
(`0.9.0.dev2`). It is not in the stable COPR release. No separate service or
mobile installation is required. Keep the desktop app open while using it.

## Try it without replacing your stable installation

Close any running ComfyUI Control window, then:

```bash
git clone --single-branch --branch testing/mobile-webui https://github.com/jhakuzi/comfyui-control.git comfyui-control-mobile
cd comfyui-control-mobile
python3 -m venv .venv-test
.venv-test/bin/python -m pip install .
.venv-test/bin/comfyui-control
```

Use the usual distribution prerequisites in the [README](../README.md).
This test environment does not replace your RPM or desktop launcher. It reads
your existing launch settings; mobile preferences are stored separately.
The stable app and testing app cannot run simultaneously for the same user.

Alternatively, [download the testing app ZIP](https://github.com/jhakuzi/comfyui-control/raw/refs/heads/testing/mobile-webui/downloads/comfyui-control.zip)
and use `bash install.sh` for the usual per-user installation. That changes the
per-user launcher; use the isolated environment above if you want an easy
return to your stable RPM.

## Connect your iPhone

<img src="screenshots/mobile-create-testing.png" alt="Mobile creation screen with a test preset" width="360">

*Chromium capture at iPhone width using a protocol-test preset; model inference is not shown.*

1. Open **Mobile WebUI…** in the desktop window.
2. Enable the feature. Set **Listen on IP** to `0.0.0.0` for IPv4 LAN/VPN access,
   or select the particular local interface IP. The default `127.0.0.1` accepts
   connections only from this computer. IPv6 interface addresses are accepted.
3. Choose a port (default **8189**) and set a password of at least 10 characters.
4. Set **Phone hostname / URL** to your computer's LAN IP, VPN IP, or VPN hostname.
   This is independent of the listening interface. Automatic detection can pick
   the wrong interface; an explicit hostname is recommended for VPN use.
5. Check **ComfyUI API URL**. It defaults to `http://127.0.0.1:8188`; change it
   if your launch flags use another port. ComfyUI itself can remain loopback-only.
6. Click **Apply**, wait for **Listening**, and scan the QR with the iPhone camera.
   Sign in with the password. The QR contains only the URL.

**Open in browser** and **Copy URL** use the same address. The QR updates when
the advertised address or port changes; apply changes before connecting.
A full HTTP(S) origin can override the advertised URL for a reverse proxy,
for example `https://comfy.your-vpn-domain.example`. Its external port is
independent of the internal listener port. Path-prefix proxying is not supported.

If you use Fedora's firewall, allow the selected port in the appropriate LAN
or VPN zone yourself. Do not open a public router port. The app makes no firewall,
router, UPnP, or VPN configuration changes. Your phone must be able to route to
the advertised address, and any configured DNS name must resolve on the phone.

## Import your workflow and map its inputs

Export an **API-format workflow** from ComfyUI. A normal node-editor JSON file
with `nodes` and `links` is not an API graph and will be rejected with instructions.
Depending on your ComfyUI frontend version, API export may be in the workflow
export menu or require enabling developer options first.

Import using either:

- **Import API workflow from this computer…** in the desktop Mobile WebUI dialog.
- **Advanced & workflows → Import a workflow** on the mobile page.

Give it a name and select it from **Workflow**. In **Advanced & workflows →
Map workflow inputs**, search for the node/input you want, then assign a role:

| Role | Example use |
| --- | --- |
| Positive / negative prompt | A text encoder's literal text input. |
| Model / checkpoint | A loader's model filename, including custom/quantized loaders. |
| LoRA model / strength / enabled | A filename, numeric strength, or boolean switch on your particular LoRA nodes. |
| Width / height / batch | Literal size and batch inputs on the appropriate image/latent nodes. |
| Steps / CFG / seed | Literal sampler inputs; expose only those your workflow uses. |
| Other advanced control | Another supported literal text, numeric, or boolean input. |

Save the mapping. Only mapped controls appear on the generation screen. No
node IDs or class names are built into the application. Choices and numeric
limits are read from ComfyUI's `/object_info`; custom loaders can provide their
own lists. If a custom widget doesn't expose its choices through that API,
its mapped filename is a text control, or you can leave its saved value alone.

Several controls can have the same role, allowing separate encoders or samplers.
Each literal input can be mapped once. Connection arrays, nested structures,
and opaque custom widget state cannot be edited by these controls and remain
unchanged. There is no automatic guess about which text node is positive or
negative. Required inputs and missing nodes are checked before/while queueing;
ComfyUI's validation errors are returned to the page.

### LoRA groups

Multiple LoRA nodes and strengths are supported. Mappings from the same node
share a group by default; edit the group name in the mapping editor to group
separate model/CLIP strength inputs when appropriate.

A group with mapped strengths can be switched off by setting those strengths
to zero in the submission copy. The stored defaults are kept for re-enabling.
A mapped boolean enable input controls that node directly instead. Nodes whose
bypass state is encoded in graph structure or opaque custom data cannot safely
be toggled this way: leave them fixed in the original workflow or expose an
appropriate literal enable/strength input in ComfyUI first.

The source file is never overwritten. The imported graph is stored separately
and every generation uses a deep copy with only explicitly mapped values changed.
Changing mappings changes the preset revision; stale generation forms and reuse
requests are rejected until reloaded.

## Generate, view, and reuse

1. Start ComfyUI using the desktop app, then choose your mobile preset.
2. Enter the prompt. Expand LoRAs or generation settings if you want to adjust them.
3. Press **Generate**. Submissions use durable request IDs so a retry or lost
   response doesn't enqueue the same request again.
4. Watch queue position, node progress, and previews where ComfyUI supplies them.
   A job may have no preview or progress count; completion is still detected.
5. Tap the completed image to view it, or open **Gallery**. Use **Save image**;
   in Safari you can also touch and hold an image to save it to Photos.

Use **Reuse last generation**, **Same seed**, or **New variation** to prepare
the next form, then press **Generate**. Fixed 64-bit seeds retain their exact
value. Randomization affects mapped seeds only. A preset without a seed mapping
keeps its original behaviour.

Queue cancellation removes only the selected prompt. Running-job cancellation
uses ComfyUI's job-specific cancellation API. Older ComfyUI versions without
that endpoint show an error; the app never falls back to global interruption.
Cancel such a running job in ComfyUI itself.

Job state is stored by the desktop app, so reloading or reconnecting restores it.
The interface shows an uncertain submission rather than blindly retrying if
ComfyUI's response was lost. Check the queue before explicitly starting a new
request in that situation. After a ComfyUI restart, history may be gone; local
output images remain browsable.

### Screen locking, app switching, and reconnecting

When Safari becomes active again (including returning from its back/forward
cache), the page reopens its live connection automatically. It shows the desktop
backend's cached sampling progress immediately, then reconciles the ComfyUI
queue and history. Images that completed while the phone was disconnected
appear automatically. A temporary VPN outage retries with a bounded backoff;
there is no recurring queue polling while connected. No generation is restarted
or submitted by this recovery path.

The desktop keeps its existing ComfyUI WebSocket open independently of the
phone. The phone uses Server-Sent Events. Sampling counters resume when ComfyUI
provides them; if the desktop itself lost its upstream connection, it resumes
live counters on the next ComfyUI progress event. Queue/history APIs cannot
invent sampling counters that ComfyUI does not expose.

The selected workflow, unsent prompt/settings, unsaved input mappings, expanded
sections, selected tab, and scroll position are saved in browser storage.
Refreshing restores these edits rather than replacing them with the last
submitted prompt. Request IDs survive connection failures to prevent duplicate
submissions. Generation controls stay disabled while recovery is in progress.

Each browser profile has a persistent HttpOnly client-identity cookie. Its
jobs, progress, previews, cancellation, and reuse metadata are isolated from
other profiles. Tabs in the same profile share that identity; presets and the
output-image gallery remain shared. Clearing site cookies or using a new
private-browsing session creates a new identity. Clearing browser storage loses
local drafts/UI state. Sign-out explicitly clears local drafts. Authentication
still expires after 12 hours, or on a mobile-server restart; signing in again
with the same identity restores its jobs.

Jobs from the earlier `0.9.0.dev1` testing build had no browser ownership and
are not assigned to a new browser automatically. Their output files remain
browsable in the gallery. This avoids exposing one client's old jobs to another.

Gallery entries reference existing output files or ComfyUI's image API; image
files are not copied into a second library. Recent history and a bounded scan
of the selected output folder populate the gallery. Mobile-created images have
saved prompt/settings metadata for reuse. Other images may have no mobile
metadata. Temporary previews and deleted files can become unavailable.

## Home-screen / PWA use

The site has a manifest, icons, standalone mode, and iPhone home-screen metadata.
Use Safari's **Share → Add to Home Screen** where supported.

HTTP over a LAN or VPN IP is generally **not a secure context**. The ordinary
website remains functional, but service workers and full installation features
depend on browser policy. Service workers are registered only in a secure
context, such as HTTPS through your own trusted reverse proxy, or localhost.
Only public shell assets are cached. Prompts, jobs, API responses, and generated
images are never put into the service-worker cache.

## Security and lifecycle

- Disabled by default; the default bind address is loopback.
- A password is mandatory beyond loopback. It is salted/hashed locally; browser
  sessions use HttpOnly, SameSite cookies. Restarting the mobile server expires sessions.
- Host and Origin checks protect against DNS rebinding and cross-site mutation.
  The advertised hostname must match how you access the site.
- There are no endpoints accepting arbitrary file paths, proxy URLs, shell
  commands, launch settings, credentials, or environment variables.
- Import only workflows and custom nodes you trust: execution has the same
  capabilities as running that workflow in ComfyUI. Unmapped literal values
  are not sent to the browser by the mapping-candidate endpoint.
- Listening on every interface may expose the port on networks beyond your VPN.
  Select an interface and appropriate firewall zone for your situation.
- Plain HTTP is not encrypted; use the VPN or HTTPS for untrusted networks.
  HTTPS is provided by your own proxy, not by a built-in certificate installer.
- Opening/closing the phone page never starts, stops, or restarts ComfyUI.
- Closing the desktop app stops the mobile listener cleanly. Its existing
  ComfyUI shutdown confirmation still applies to owned running processes.

Files live under the app's config directory (`~/.config/comfyui-control/mobile`
by default): `settings.json`, `presets/`, and `jobs.json`. The original launch
configuration remains in `config.json`. Treat this directory as private: it
contains your workflow text and prompts, as well as a password hash.

## Architecture and testing

See [the architecture and verification notes](MOBILE_ARCHITECTURE.md) for module
boundaries, protocol tests, and the limits of what has actually been verified.
Physical iPhone Safari, your VPN/LAN routing, HTTPS proxying, and your particular
GPU/quantized-model/LoRA workflows still require testing on your own installation.
