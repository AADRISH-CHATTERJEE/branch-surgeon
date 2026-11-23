import { EDGE_LEGEND, FILTER_GROUPS, NODE_TYPE_STYLES } from "../lib/graph-styles";

export function GraphLegend() {
  return (
    <div className="rounded-lg border bg-card/80 p-3 text-xs backdrop-blur">
      <p className="mb-2 font-semibold">Legend</p>
      <div className="mb-3 space-y-1.5">
        <p className="text-2xs uppercase text-muted-foreground">Nodes</p>
        {FILTER_GROUPS.map((g) => {
          const sampleType = g.types[0]!;
          const style = NODE_TYPE_STYLES[sampleType];
          return (
            <div key={g.key} className="flex items-center gap-2">
              <span
                className="inline-block size-2.5 rounded-sm"
                style={{ background: style?.color }}
              />
              <span>{g.label}</span>
            </div>
          );
        })}
      </div>
      <div className="space-y-1.5">
        <p className="text-2xs uppercase text-muted-foreground">Edges</p>
        {EDGE_LEGEND.map((e) => (
          <div key={e.key} className="flex items-center gap-2">
            <span
              className="inline-block h-0.5 w-5"
              style={{
                background: e.stroke,
                backgroundImage: e.dashed
                  ? `repeating-linear-gradient(90deg, ${e.stroke} 0 3px, transparent 3px 6px)`
                  : undefined,
              }}
            />
            <span>{e.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
