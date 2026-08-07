/**
 * Push-to-talk. An accelerator, never a mode.
 *
 * Web Speech API first (zero upload, zero latency), `MediaRecorder` + Whisper as the
 * fallback, and if neither is available the button hides itself rather than sitting
 * there broken. The typed input stays visible and usable throughout.
 *
 * The transcript always lands in the normal input field, editable, before anything
 * happens with it. No voice input ever triggers a write on its own — the caller shows
 * a confirm step for anything that changes state.
 */

import { AudioOutlined, LoadingOutlined } from "@ant-design/icons";
import { App, Button, Tooltip } from "antd";
import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";

type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: any) => void) | null;
  onerror: ((event: any) => void) | null;
  onend: (() => void) | null;
};

function getRecognition(): SpeechRecognitionLike | null {
  const Ctor =
    (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition ?? null;
  if (!Ctor) return null;
  const recognition: SpeechRecognitionLike = new Ctor();
  recognition.lang = "en-GB";
  recognition.interimResults = true;
  recognition.continuous = false;
  return recognition;
}

const canRecord = () =>
  typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia;

interface VoiceButtonProps {
  /** Receives the transcript. Put it in the input field — do not act on it. */
  onTranscript: (text: string) => void;
  /** Live partial text, for showing what is being heard. */
  onInterim?: (text: string) => void;
  disabled?: boolean;
  size?: "small" | "middle" | "large";
}

export default function VoiceButton({ onTranscript, onInterim, disabled, size = "middle" }: VoiceButtonProps) {
  const { message: toast } = App.useApp();
  const [state, setState] = useState<"idle" | "listening" | "transcribing">("idle");
  const [supported, setSupported] = useState(true);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    setSupported(!!getRecognition() || canRecord());
    return () => {
      recognitionRef.current?.stop();
      recorderRef.current?.stop();
    };
  }, []);

  if (!supported) return null;

  function startSpeechApi(recognition: SpeechRecognitionLike) {
    recognitionRef.current = recognition;
    let finalText = "";

    recognition.onresult = (event: any) => {
      let interim = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal) finalText += result[0].transcript;
        else interim += result[0].transcript;
      }
      if (interim) onInterim?.(interim);
    };
    recognition.onerror = (event: any) => {
      setState("idle");
      // Falls back to typing silently — a mic that refuses is not an error worth a modal.
      if (event?.error !== "aborted") toast.info("Voice input unavailable — type instead");
    };
    recognition.onend = () => {
      setState("idle");
      if (finalText.trim()) onTranscript(finalText.trim());
    };

    recognition.start();
    setState("listening");
  }

  async function startRecorder() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      chunksRef.current = [];

      recorder.ondataavailable = (event) => chunksRef.current.push(event.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        setState("transcribing");
        try {
          const { data } = await api.transcribe(new Blob(chunksRef.current, { type: "audio/webm" }));
          if (data.text?.trim()) onTranscript(data.text.trim());
        } catch {
          toast.info("Could not transcribe that — type instead");
        } finally {
          setState("idle");
        }
      };

      recorder.start();
      setState("listening");
    } catch {
      setState("idle");
      toast.info("Microphone permission denied — type instead");
    }
  }

  function toggle() {
    if (state === "listening") {
      recognitionRef.current?.stop();
      recorderRef.current?.stop();
      return;
    }
    if (state === "transcribing") return;

    const recognition = getRecognition();
    if (recognition) startSpeechApi(recognition);
    else void startRecorder();
  }

  const label =
    state === "listening" ? "Stop listening" : state === "transcribing" ? "Transcribing" : "Dictate";

  return (
    <Tooltip title={`${label} — the transcript lands in the field, editable, before anything happens`}>
      <Button
        size={size}
        disabled={disabled}
        aria-label={label}
        aria-pressed={state === "listening"}
        className={state === "listening" ? "voice-listening" : undefined}
        danger={state === "listening"}
        icon={state === "transcribing" ? <LoadingOutlined /> : <AudioOutlined />}
        onClick={toggle}
      />
    </Tooltip>
  );
}
