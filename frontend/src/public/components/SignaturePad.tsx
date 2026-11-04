// A finger-drawn signature, using the `signature_pad` package (decision
// 0031). It reports the drawing as a PNG data URL, or null while the pad
// is empty; the server checks the image and puts it in the PDF snapshot.
import { useEffect, useRef } from "react";
import SignaturePadLib from "signature_pad";

type Props = {
  onChange: (png: string | null) => void;
  label: string;
};

export function SignaturePad({ onChange, label }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const padRef = useRef<SignaturePadLib | null>(null);
  // The latest callback, so the pad's listener never goes stale.
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const pad = new SignaturePadLib(canvas, { penColor: "black" });
    padRef.current = pad;

    // The canvas is drawn at the screen's real pixel density, so the
    // signature is sharp. Refitting clears it (the package's own advice:
    // scaling a drawing distorts it), so it happens only when the pad's
    // width changes, as on turning the phone. Phones also fire `resize`
    // when the keyboard opens or the toolbar hides on scrolling; those
    // change only the height and must keep the signature.
    let fittedWidth = -1;
    function fit() {
      if (!canvas || canvas.offsetWidth === fittedWidth) return;
      fittedWidth = canvas.offsetWidth;
      const ratio = Math.max(window.devicePixelRatio || 1, 1);
      canvas.width = canvas.offsetWidth * ratio;
      canvas.height = canvas.offsetHeight * ratio;
      canvas.getContext("2d")?.scale(ratio, ratio);
      pad.clear();
      onChangeRef.current(null);
    }
    fit();
    window.addEventListener("resize", fit);

    const ended = () =>
      onChangeRef.current(pad.isEmpty() ? null : pad.toDataURL("image/png"));
    pad.addEventListener("endStroke", ended);

    return () => {
      window.removeEventListener("resize", fit);
      pad.removeEventListener("endStroke", ended);
      pad.off();
      padRef.current = null;
    };
  }, []);

  function clear() {
    padRef.current?.clear();
    onChange(null);
  }

  return (
    <div>
      <p>{label}</p>
      <canvas
        ref={canvasRef}
        aria-label={label}
        style={{
          width: "100%",
          maxWidth: "500px",
          height: "180px",
          border: "1px solid",
          touchAction: "none",
          display: "block",
        }}
      />
      <button type="button" onClick={clear}>
        ניקוי החתימה
      </button>
    </div>
  );
}
