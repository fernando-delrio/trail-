import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

export default function RouteRegistrationBottomNav({
  onStart,
  isRecording = false,

  fabTo = null,

  fabLabel,
  fabTitle,
  fabIcon,
}) {
  const navigate = useNavigate();

  const computed = useMemo(() => {
    const defaultLabel = isRecording ? "Detener registro" : "Iniciar";
    const defaultTitle = isRecording ? "Stop" : "Start";
    const defaultIcon = isRecording ? "■" : "▶";

    return {
      label: fabLabel ?? defaultLabel,
      title: fabTitle ?? defaultTitle,
      icon: fabIcon ?? defaultIcon,
    };
  }, [fabIcon, fabLabel, fabTitle, isRecording]);

  const handleFabClick = () => {
    if (fabTo) return navigate(fabTo);
    if (typeof onStart === "function") return onStart();
  };

  return (
    <div className="rr-bottom">
      <div className="rr-bottom-nav rr-bottom-nav--single">
        <button
          type="button"
          className={`rr-fab ${isRecording ? "rr-fab--stop" : ""}`}
          title={computed.title}
          onClick={handleFabClick}
        >
          {computed.icon}
        </button>
      </div>
    </div>
  );
}
