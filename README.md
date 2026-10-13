# Leap Motion to Blender Live Link

Real-time Ultraleap hand tracking over local UDP, updated for **Blender 5.2 LTS**.
Tested on Windows with **Blender 5.2.2 LTS**, **Python 3.14**, and an **Orion 4.0**
tracking service. The Blender extension has no third-party Python dependencies.

The sender runs in a separate Python process. It uses CFFI ABI mode to load LeapC,
so it needs neither a C compiler nor a Python-version-specific `leapc_cffi` build.
The upstream bindings in `repo_temp` are retained as a reference; their example
installation commands are **not needed for this live link**.

## What can I use this for?

A rig is a skeleton of bones that can control a 3D model. Normally you pose those
bones by hand; this link updates their poses from your real hands. The generated
stick skeleton is a way to check the tracking before connecting it to visible
models or other behavior.

**Available now:** live tracking of both hands and forearms, a generated debug
rig, connection status, and a hardware-free animated demo. You can inspect joint
movement and use the tracked bones as inputs to your own Blender setup.

Possible applications with additional setup:

- **Animate a visible hand:** attach a hand mesh to the tracked bones with an
  Armature modifier and vertex weights. The weights determine which bones move
  each part of the mesh; the included debug rig has no skin or hand mesh.
- **Capture animation:** add recording that saves the changing bone poses as
  keyframes on Blender's timeline, then clean up and edit the result. Moving the
  live rig or playing the timeline does not automatically record its poses.
- **Drive a character's hands:** map the tracked bones to the character's hand
  rig. This mapping is called retargeting. Arbitrary character rigs need a
  mapping or constraints; their bone names and rest poses usually differ.
- **Build gesture controls:** use fingertip positions to detect a pinch, then
  add rules to grab, move or release an object. Gesture recognition and object
  interaction are not built into this add-on.
- **Make visual effects:** use a tracked fingertip bone as the source for an
  effect or trail. Live effects need a suitable scene setup; reusable animation
  and rendered motion need recording or baking first.

For example, a finished character-wave workflow would be: connect the character's
hand rig, record yourself waving, edit the captured keyframes, and render the
shot. This project currently supplies the live tracking stage of that workflow.
It does not include a hand mesh, animation recording, automatic retargeting,
gesture controls, or an avatar streaming/export integration.

## Quick start on Windows

You need 64-bit Python, Blender 5.2 LTS, and a connected controller with its
tracking software installed. Clone or download this repository and open a terminal
in its root folder. For the demo, the controller and tracking software are optional.

```powershell
.\run.cmd setup
.\run.cmd check
.\run.cmd launch
```

- `setup` creates `.venv` and installs the sender's CFFI dependency.
- `check` verifies the native library, tracking service, controller and frames.
- `launch` opens a **new scratch Blender scene**, generates both hands, starts the
  receiver and starts its sender in the background. Close Blender to stop that sender.

After setup you can also double-click **Launch Live Link.cmd**. Open the 3D View
sidebar with **N**, select **Leap Link**, and move your hands above the controller.
The panel reports the source, visible hand count and received updates.
Use **Object Mode** or **Pose Mode**. Entering **Edit Mode** stops the receiver;
return to Object/Pose Mode and click **Start Receiver** to resume.

To try animated hands without hardware, double-click **Launch Demo.cmd** or run:

```powershell
.\run.cmd launch-demo
```

The `.cmd` launchers set PowerShell's execution policy only for their own process.
They do not change your machine's execution-policy settings.

The launcher expects Blender at
`C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`. Override its path
when necessary:

```powershell
.\run.cmd launch -Blender "D:\Apps\Blender 5.2\blender.exe"
```

`launch` and `launch-demo` start a new Blender instance with factory startup.
Use the existing-scene instructions below to work in your own project.

## Use in an existing Blender scene

1. Build the extension with `.\run.cmd build`.
2. In Blender 5.2, open **Edit > Preferences > Add-ons**, open the menu at the top
   right and choose **Install from Disk**.
3. Select `dist/leap_live_link-1.1.0.zip` and enable **Leap Motion Live Link**.
4. In **3D View > N > Leap Link**, click **Generate Debug Hands** and **Start Receiver**.
5. Run `.\run.cmd sender` in a terminal. **Ctrl+C** stops this standalone sender.

Use `.\run.cmd demo` for a synthetic sender connected to an existing receiver.
Only one receiver can bind a given UDP port. Stop a previous receiver before
opening another session on the same port.

## Tracking software and Python

Connect a Leap Motion / Ultraleap controller and start its tracking service.
For Orion, Windows calls this service **Leap Service** (`LeapService`). Starting
it may require administrator privileges; in an administrator PowerShell run:

```powershell
Start-Service LeapService
```

The sender automatically selects an installed Ultraleap SDK, or the Orion client
included with `C:\Program Files\Leap Motion\Core Services\VRVisualizer` if present.
Otherwise it uses the vendored Windows x64 LeapC client. A new client is not always
compatible with an older tracking service; use the client matching your service.
The Orion path uses the stable hand/frame ABI shared with the vendored header.

For a custom Gemini/Hyperion SDK, use its matching header and library:

```powershell
.\.venv\Scripts\python.exe sender\sender.py --sdk "C:\Program Files\Ultraleap\LeapSDK"
```

`LEAPSDK_INSTALL_LOCATION` can also select the SDK. Windows requires 64-bit Python.
The sender has been tested with Python 3.14; Blender uses its own Python and does
not need CFFI installed. The bundled native library is Windows-only; Linux/macOS
require an external SDK via `--sdk` and have not been tested.

If you prefer manual setup:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r sender\requirements.txt
.\.venv\Scripts\python.exe sender\sender.py --check
.\.venv\Scripts\python.exe sender\sender.py
```

Do not `pip install` the upstream repository root: it is not a Python package.
No Git-based Python dependency or editable upstream installation is required.

## Rig and receiver behavior

- Generates **44 bones**: two wrists, two forearms and twenty finger segments
  per hand. Existing objects are preserved; a generated target rig is reused.
- Joint endpoints control bone position, direction and length. Sensor rotations
  provide finger roll. Disconnected bones avoid forcing tracked joints onto
  parent tails, and explicit parent-space conversion avoids stale parent poses.
- Leap coordinates in millimetres `(x, y, z)` become Blender `(x, -z, y)`.
  **Units per mm** defaults to `0.001`. Tracking is in armature space: move,
  rotate or scale the rig object to place the hands in your scene.
- Custom armatures must use the generated names, such as `L_Wrist`,
  `R_Forearm`, and `L_Index_Proximal`. Automatic retargeting to arbitrary
  character rigs and animation recording are not included.
- The receiver uses Blender's main-thread application timer, processes the
  latest valid queued frame, and releases its socket immediately on Stop,
  add-on disable or file load. Leave Edit Mode before receiving poses.
- Empty hand frames update the hand count to zero. Missing hands hold their last
  pose. If the sender stops, the panel reports stale data after one second.
- The receiver listens only on `127.0.0.1`. Its port defaults to `9009`.
  Sender and receiver ports must match.

For a different port or tracking mode:

```powershell
.\run.cmd launch -Port 9010 -Mode desktop
.\run.cmd sender -Port 9010 -Mode hmd
```

Modes: `desktop`, `hmd`, `screen-top`. Orion supports desktop and HMD only.

## Verification and troubleshooting

```powershell
.\run.cmd test
.\run.cmd build
```

Tests run inside real Blender 5.2 and check both hands' joint endpoints across
changing poses, wrist rotation, finger lengths, zero-length thumb bones, scaling,
real UDP delivery from a separate sender, empty and malformed packets, port
conflicts, teardown and restart. Native tests verify the packed ABI and serializer.
The extension build is validated by Blender's own extension tools.

An optional hardware test compares incoming tracked joints with the evaluated
Blender rig. Place a hand above the controller while running it:

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python tests\blender_live.py
```

The normal `test` command needs no controller. The optional live test requires
a running tracking service and at least one visible hand.

For launch sessions, `.test-output/sender.log` contains sender diagnostics and
`.test-output/live-status.json` contains current connection counters. No raw hand
frames are written to disk. Standalone `sender` / `check` commands print to the terminal.

- **Service not connected:** start the service and check that the client matches
  its version. The service can be running while an incompatible client fails to connect.
- **No controller detected:** check USB, the tracking software's visualizer, and
  the controller driver. A service connection alone does not prove camera tracking.
- **Zero hands:** put your hands in the camera's view and use the correct tracking mode.
- **Port already in use:** stop the other receiver or change both ports.
- **No motion:** verify a target armature, leave Edit Mode, check panel status and
  run `launch-demo` to separate Blender/UDP issues from controller tracking.

## 日本語

Blender **5.2 LTS** 用のリアルタイムハンドトラッキングです。
生成されるリグは、実際の手の動きで骨を動かす動作確認用のスケルトンです。
手の 3D モデルを接続すればモデルを動かせます。アニメーションの収録、
キャラクターへのリターゲット、ピンチ操作、視覚効果などにも応用できますが、
それぞれ追加の設定や実装が必要です。この版には手のメッシュ、自動収録、
自動リターゲット、ジェスチャーによるオブジェクト操作は含まれません。

プロジェクトのルートで `run.cmd setup`、`run.cmd check`、`run.cmd launch` を実行します。
セットアップ後は **Launch Live Link.cmd** のダブルクリックでも起動できます。
**Launch Demo.cmd** は機器なしで動作確認できるデモです。

Blender の 3D ビューで **N > Leap Link** を開いて受信状況を確認してください。
**Object Mode** または **Pose Mode** を使用します。**Edit Mode** に入ると受信が停止するため、
モードを戻して **Start Receiver** を押してください。
既存のシーンでは `run.cmd build` で作成した
`dist/leap_live_link-1.1.0.zip` を **Preferences > Add-ons > Install from Disk**
からインストールし、**Generate Debug Hands > Start Receiver** を選び、
別のターミナルで `run.cmd sender` を実行してください。

送信側は Blender の外で動作します。C コンパイラや `repo_temp` 内のサンプル用依存関係は不要です。
Orion を使用する場合は **Leap Service** を起動してください。手が見えない場合は最後の姿勢を保持します。

## License

[MIT](LICENSE). Vendored Ultraleap bindings/header: [Apache-2.0](repo_temp/LICENSE.md).
