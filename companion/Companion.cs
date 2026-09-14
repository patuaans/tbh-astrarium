using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Reflection;
using System.Text;
using System.Threading;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using Il2CppInterop.Runtime.Injection;
using TaskbarHero.UI;
using UnityEngine;
using UnityEngine.UI;

namespace TBHAstrarium.Companion;

[BepInPlugin(PluginGuid, PluginName, PluginVersion)]
public sealed class Plugin : BasePlugin
{
    // Keep the legacy GUID and pipe so existing installations can upgrade in place.
    public const string PluginGuid = "local.tbhstargaze.companion";
    public const string PluginName = "TBH Astrarium Companion";
    public const string PluginVersion = "0.2.1";
    internal const string PipeName = "TBHStargaze.Companion.v1";

    internal static ManualLogSource PluginLog = null;
    internal static ConfigEntry<float> Cooldown = null;
    internal static readonly ConcurrentQueue<string> Commands = new();

    public override void Load()
    {
        PluginLog = Log;
        Cooldown = Config.Bind("Auto Unbox", "Cooldown seconds", 0.25f,
            new ConfigDescription("Time between chest candidates.", new AcceptableValueRange<float>(0.1f, 10f)));
        ClassInjector.RegisterTypeInIl2Cpp<AutoUnboxRunner>();
        AddComponent<AutoUnboxRunner>();
        StartCommandServer();
        Log.LogInfo("TBH Astrarium Companion 0.2 loaded for the current game API.");
    }

    private static void StartCommandServer()
    {
        new Thread(() =>
        {
            while (true)
            {
                try
                {
                    using var pipe = new NamedPipeServerStream(PipeName, PipeDirection.In, 1,
                        PipeTransmissionMode.Byte, PipeOptions.None);
                    pipe.WaitForConnection();
                    using var reader = new StreamReader(pipe, Encoding.UTF8, false, 256, true);
                    var command = reader.ReadLine();
                    if (!string.IsNullOrWhiteSpace(command)) Commands.Enqueue(command.Trim());
                }
                catch (Exception error)
                {
                    PluginLog?.LogWarning($"Command bridge error: {error.Message}");
                }
            }
        }) { IsBackground = true, Name = "TBHAstrarium command bridge" }.Start();
    }
}

public sealed class AutoUnboxRunner : MonoBehaviour
{
    private bool _active;
    private float _nextOpenAt;
    private MethodInfo _getButton;
    private MethodInfo _tryOpen;
    private bool _reportedUnavailable;
    private float _nextDiagnosticAt;
    private int _nextBoxIndex;

    public AutoUnboxRunner(IntPtr pointer) : base(pointer) { }

    public void Update()
    {
        while (Plugin.Commands.TryDequeue(out var command))
        {
            if (string.Equals(command, "autounbox:on", StringComparison.OrdinalIgnoreCase))
            {
                _active = true;
                Plugin.PluginLog.LogInfo("Auto Unbox enabled by TBH Astrarium.");
            }
            else if (string.Equals(command, "autounbox:off", StringComparison.OrdinalIgnoreCase))
            {
                _active = false;
                Plugin.PluginLog.LogInfo("Auto Unbox disabled by TBH Astrarium.");
            }
        }
        if (!_active || Time.unscaledTime < _nextOpenAt) return;
        TryOpenOne();
    }

    private void ResolveStageBoxApi()
    {
        if (_getButton != null && _tryOpen != null) return;
        foreach (var method in typeof(StageBox).GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
        {
            if (method.GetParameters().Length != 0) continue;
            if (_getButton == null && method.ReturnType == typeof(Button)) _getButton = method;
            if (_tryOpen == null && method.ReturnType.FullName != null &&
                method.ReturnType.FullName.StartsWith("Cysharp.Threading.Tasks.UniTask`1") &&
                method.ReturnType.GenericTypeArguments.Length == 1 &&
                method.ReturnType.GenericTypeArguments[0] == typeof(bool)) _tryOpen = method;
        }
    }

    private void TryOpenOne()
    {
        try
        {
            ResolveStageBoxApi();
            if (_getButton == null || _tryOpen == null)
            {
                if (!_reportedUnavailable)
                {
                    _reportedUnavailable = true;
                    Plugin.PluginLog.LogError("Auto Unbox unavailable: the current StageBox API was not found.");
                }
                _active = false;
                return;
            }
            var boxes = Resources.FindObjectsOfTypeAll<StageBox>();
            var candidates = new List<StageBox>();
            var primaryCandidates = new List<StageBox>();
            foreach (var box in boxes)
            {
                if (box == null) continue;
                var button = _getButton.Invoke(box, null) as Button;
                if (button == null || !button.interactable) continue;
                candidates.Add(box);
                var name = box.name ?? string.Empty;
                if (!name.Contains("Small") && !name.Contains("Plague")) primaryCandidates.Add(box);
            }
            var selectedCandidates = primaryCandidates.Count > 0 ? primaryCandidates : candidates;
            if (selectedCandidates.Count > 0)
            {
                var box = selectedCandidates[_nextBoxIndex % selectedCandidates.Count];
                _nextBoxIndex = (_nextBoxIndex + 1) % selectedCandidates.Count;
                _nextOpenAt = Time.unscaledTime + Plugin.Cooldown.Value;
                _tryOpen.Invoke(box, null);
                Plugin.PluginLog.LogInfo($"Auto Unbox requested one chest from '{box.name}'.");
                return;
            }
            if (Time.unscaledTime >= _nextDiagnosticAt)
            {
                _nextDiagnosticAt = Time.unscaledTime + 10f;
                Plugin.PluginLog.LogInfo($"Auto Unbox waiting: {boxes.Length} StageBox instance(s), no enabled chest buttons.");
            }
        }
        catch (TargetInvocationException error)
        {
            Plugin.PluginLog.LogWarning($"Auto Unbox rejected by the game: {error.InnerException?.Message ?? error.Message}");
            _nextOpenAt = Time.unscaledTime + Plugin.Cooldown.Value;
        }
        catch (Exception error)
        {
            Plugin.PluginLog.LogWarning($"Auto Unbox failed safely: {error.Message}");
            _nextOpenAt = Time.unscaledTime + Plugin.Cooldown.Value;
        }
    }
}
