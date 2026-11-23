/** Browser speech synthesis for bilingual warnings and a local siren. */

let activeUtterances = 0;

function pickVoice(language: string): SpeechSynthesisVoice | null {
  if (typeof window === "undefined" || !window.speechSynthesis) return null;
  const voices = window.speechSynthesis.getVoices();
  const prefix = language.toLowerCase().slice(0, 2);
  const candidates = voices.filter((voice) => voice.lang.toLowerCase().startsWith(prefix));
  if (!candidates.length) return null;
  const preferred = candidates.find((voice) => /google|natural|premium|siri/i.test(voice.name));
  return preferred ?? candidates[0];
}

export function speechSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function cancelSpeech(): void {
  if (!speechSupported()) return;
  activeUtterances = 0;
  window.speechSynthesis.cancel();
}

export function speak(
  messages: { language: string; text: string }[],
  options: { onEnd?: () => void; rate?: number } = {},
): void {
  if (!speechSupported() || !messages.length) {
    options.onEnd?.();
    return;
  }
  cancelSpeech();
  const queue = [...messages];
  activeUtterances = queue.length + 1;

  const next = () => {
    activeUtterances -= 1;
    const item = queue.shift();
    if (!item) {
      if (activeUtterances <= 0) options.onEnd?.();
      return;
    }
    const utterance = new SpeechSynthesisUtterance(item.text);
    utterance.lang = item.language.startsWith("ar") ? "ar-SA" : "en-US";
    const voice = pickVoice(utterance.lang);
    if (voice) utterance.voice = voice;
    utterance.rate = options.rate ?? 0.94;
    utterance.pitch = 1;
    utterance.volume = 1;
    utterance.onend = next;
    utterance.onerror = next;
    window.speechSynthesis.speak(utterance);
  };

  // Voices can load asynchronously on the first call.
  if (window.speechSynthesis.getVoices().length === 0) {
    window.speechSynthesis.onvoiceschanged = () => {
      window.speechSynthesis.onvoiceschanged = null;
      next();
    };
    window.setTimeout(() => {
      if (activeUtterances > 0 && !window.speechSynthesis.speaking) {
        window.speechSynthesis.onvoiceschanged = null;
        next();
      }
    }, 400);
  } else {
    next();
  }
}

let sirenTimer: number | null = null;
let audioContext: AudioContext | null = null;

export function stopSiren(): void {
  if (sirenTimer !== null) {
    window.clearTimeout(sirenTimer);
    sirenTimer = null;
  }
  if (audioContext) {
    audioContext.close().catch(() => undefined);
    audioContext = null;
  }
}

/** Short local siren used when the Emergency Response Engine is armed. */
export function playSiren(seconds = 6): void {
  if (typeof window === "undefined") return;
  stopSiren();
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return;
  const context = new Ctor();
  audioContext = context;
  const gain = context.createGain();
  gain.gain.value = 0.14;
  gain.connect(context.destination);

  const oscillator = context.createOscillator();
  oscillator.type = "sawtooth";
  oscillator.frequency.value = 640;
  const lfo = context.createOscillator();
  lfo.type = "sine";
  lfo.frequency.value = 0.9;
  const lfoGain = context.createGain();
  lfoGain.gain.value = 240;
  lfo.connect(lfoGain);
  lfoGain.connect(oscillator.frequency);

  oscillator.connect(gain);
  oscillator.start();
  lfo.start();
  sirenTimer = window.setTimeout(() => stopSiren(), Math.max(1000, seconds * 1000));
}
