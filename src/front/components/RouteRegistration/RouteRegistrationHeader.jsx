export default function RouteRegistrationHeader({
  searchValue,
  onSearchChange,
  onSearchSubmit,
  activeFilter,
  onFilterChange,
}) {
  const filters = [
    { id: "gravel",    label: "GRAVEL" },
    { id: "xc",        label: "XC" },
    { id: "trail",     label: "TRAIL" },
    { id: "enduro",    label: "ENDURO" },
    { id: "downhill",  label: "DOWNHILL" },
    { id: "carretera", label: "CARRETERA" },
  ];

  return (
    <div className="rr-header">
      <form
        className="rr-search"
        onSubmit={(e) => {
          e.preventDefault();
          onSearchSubmit?.();
        }}
      >
        <span className="rr-search-icon">⌕</span>

        <input
          value={searchValue}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Buscar rutas o lugares"
        />

        <button
          className="rr-search-btn"
          type="submit"
          aria-label="Buscar"
          title="Buscar"
        >
          ↵
        </button>
      </form>


      <div className="rr-chips">
        {filters.map((f) => (
          <button
            key={f.id}
            type="button"
            className={`rr-chip ${activeFilter === f.id ? "active" : ""}`}
            onClick={() => onFilterChange?.(f.id)}
          >
            {f.label}
          </button>
        ))}
      </div>
    </div>
  );
}
