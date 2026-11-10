#!/home/user/agent-mission-control-os/.venv/bin/python
"""espeak-ng CLI-compatible shim backed by the real libespeak-ng engine
(bundled by the espeakng-loader wheel). Implements only the flags used by
FreeVideoForge's espeak provider: --version, -v, -s, -p, -g, -w, and the
trailing text argument. Output is 16-bit mono PCM WAV at espeak's native rate.
"""
import sys, wave, ctypes

VSYNC = 0x0002          # AUDIO_OUTPUT_SYNCHRONOUS
CHARS_UTF8 = 0x0002     # espeakCHARS_UTF8
P_RATE, P_PITCH, P_WORDGAP = 1, 3, 5

def main() -> int:
    args = sys.argv[1:]
    if "--version" in args:
        print("eSpeak NG text-to-speech: libespeak-ng via espeakng-loader (local, offline)")
        return 0
    voice, rate, pitch, gap, out = "en-us", 160, 42, 4, None
    it = iter(range(len(args)))
    i = 0
    text = None
    while i < len(args):
        a = args[i]
        if a == "-v": voice = args[i + 1]; i += 2
        elif a == "-s": rate = int(args[i + 1]); i += 2
        elif a == "-p": pitch = int(args[i + 1]); i += 2
        elif a == "-g": gap = int(args[i + 1]); i += 2
        elif a == "-w": out = args[i + 1]; i += 2
        else: text = a; i += 1
    if out is None:
        print("shim: -w <output.wav> is required", file=sys.stderr); return 2
    text = text if text is not None else " "

    import espeakng_loader
    lib = ctypes.CDLL(espeakng_loader.get_library_path())
    data = espeakng_loader.get_data_path().encode()

    lib.espeak_Initialize.restype = ctypes.c_int
    lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
    lib.espeak_SetParameter.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]

    C_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)
    lib.espeak_SetSynthCallback.argtypes = [C_CB]
    lib.espeak_Synth.restype = ctypes.c_int
    lib.espeak_Synth.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_ulong,
                                 ctypes.c_int, ctypes.c_ulong, ctypes.c_uint,
                                 ctypes.POINTER(ctypes.c_uint), ctypes.c_void_p]

    rate_hz = lib.espeak_Initialize(VSYNC, 10000, data, 0)
    if rate_hz <= 0:
        print("shim: espeak_Initialize failed", file=sys.stderr); return 1
    lib.espeak_SetVoiceByName(voice.encode())
    lib.espeak_SetParameter(P_RATE, rate, 0)
    lib.espeak_SetParameter(P_PITCH, pitch, 0)
    lib.espeak_SetParameter(P_WORDGAP, gap, 0)

    samples = []
    def _cb(wav, n, events):
        if n and n > 0:
            samples.extend(wav[j] for j in range(n))
        return 0
    cb = C_CB(_cb)
    lib.espeak_SetSynthCallback(cb)

    payload = text.encode("utf-8")
    rc = lib.espeak_Synth(payload, len(payload) + 1, 0, 0, 0, CHARS_UTF8, None, None)
    if rc != 0:
        print(f"shim: espeak_Synth returned {rc}", file=sys.stderr); return 1
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(rate_hz)
        wf.writeframes(b"".join(int(s).to_bytes(2, "little", signed=True) for s in samples))
    return 0

if __name__ == "__main__":
    sys.exit(main())
