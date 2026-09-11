# UProject Launcher

UProject Launcher opens an Unreal Engine project with selected engine plugins enabled only for that editor process. The project descriptor remains unchanged.

Launch settings appear on the left and the plugin list on the right. The settings scroll in smaller windows; Save and Launch Project remain visible below the plugin list. Both the standalone launcher and UE Forge use this layout.

Drop a single `.ulaunch` file onto either launcher panel to open it for editing. Unsaved changes require confirmation before another profile opens. Dropping a profile does not launch Unreal Editor.

## Profile format

A `.ulaunch` profile is JSON:

```json
{
  "FileVersion": 1,
  "Project": "MyProject.uproject",
  "Engine": "C:/Program Files/Epic Games/UE_5.8",
  "Plugins": [
    {
      "Name": "MyLocalPlugin",
      "Enabled": true
    }
  ],
  "Arguments": "-log -NoSplash"
}
```

`Project` can be absolute or relative to the profile. When omitted, the launcher uses the `.uproject` beside the profile with the same base name. `Engine` can be an engine root path or a registered version. Auto Detect fills both fields from the profile name and the project's `EngineAssociation`. Disabled plugin entries remain in the profile but are not passed to Unreal Editor.

Auto Detect requires the project `EngineAssociation` to match a registered engine. A manually entered engine root can also be used. Plugin scanning reads that engine's `Engine/Plugins` directory and supports filtering by plugin name, author, version, and description.

The profile is local data. The launcher does not modify `.gitignore` or `.git/info/exclude`.

The standalone launcher accepts a profile path. Associate `.ulaunch` with the standalone executable in Windows to launch a project by double-clicking its profile. Passing `--open` opens the same profile for editing without launching.
