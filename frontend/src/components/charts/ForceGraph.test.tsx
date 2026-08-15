import { createRef } from "react";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { GraphData } from "@/api/types";
import { ForceGraph } from "./ForceGraph";
import type { ForceGraphHandle } from "./forceGraphTypes";

const graphInstance = {
  zoom: vi.fn(),
  fitView: vi.fn(),
  fitCenter: vi.fn(),
};

const palette = {
  entityColors: {},
  relationColors: {},
  auxColors: {
    background: "#fff",
    positive: "#0f0",
    neutral: "#999",
    text: "#333",
  },
};

const model = {
  g6Data: { nodes: [], edges: [] },
  filteredNodes: [],
  filteredEdges: [],
  orderedLayoutNodes: [],
  nodeDegrees: new Map(),
  degreeRange: { min: 0, max: 0 },
};

const buildForceGraphModelMock = vi.fn((args: unknown) => {
  void args;
  return model;
});
const createForceGraphPaletteMock = vi.fn(() => palette);
const useG6ForceGraphMock = vi.fn((args: unknown) => {
  const options = args as { onGraphReady: (graph: typeof graphInstance) => void };
  options.onGraphReady(graphInstance);
});

vi.mock("./forceGraph/forceGraphDataAdapter", () => ({
  buildForceGraphModel: (args: unknown) => buildForceGraphModelMock(args),
}));

vi.mock("./forceGraph/forceGraphPalette", () => ({
  createForceGraphPalette: () => createForceGraphPaletteMock(),
}));

vi.mock("./forceGraph/useG6ForceGraph", () => ({
  useG6ForceGraph: (args: unknown) => useG6ForceGraphMock(args),
}));

function createGraphData(): GraphData {
  return {
    graph_version_id: "graph-version-1",
    chapter_id: 1,
    chapter_order: 1,
    first_chapter_id: 1,
    last_chapter_id: 1,
    nodes: [
      {
        entity_id: 1,
        name: "白芷",
        entity_type: "character",
        first_seen_chapter: 1,
        last_seen_chapter: 1,
        state_revision: 1,
        state: {},
      },
    ],
    edges: [],
  };
}

describe("ForceGraph", () => {
  it("会把编排后的 model/palette 交给 G6 hook，并暴露缩放控制句柄", () => {
    const ref = createRef<ForceGraphHandle>();
    const onNodeClick = vi.fn();
    const relationFilter = new Set(["盟友"]);
    const appearanceCountMap = new Map([["1", 3]]);
    const data = createGraphData();

    const { container } = render(
      <ForceGraph
        ref={ref}
        data={data}
        onNodeClick={onNodeClick}
        searchQuery="白"
        relationFilter={relationFilter}
        appearanceCountMap={appearanceCountMap}
        className="graph-shell"
      />,
    );

    expect(buildForceGraphModelMock).toHaveBeenCalledWith({
      data,
      relationFilter,
      appearanceCountMap,
    });
    expect(createForceGraphPaletteMock).toHaveBeenCalledTimes(1);
    expect(useG6ForceGraphMock).toHaveBeenCalledWith(
      expect.objectContaining({
        model,
        palette,
        searchQuery: "白",
        appearanceCountMap,
        onNodeClick,
      }),
    );

    ref.current?.zoomIn();
    ref.current?.zoomOut();
    ref.current?.fitToScreen();
    ref.current?.center();

    expect(graphInstance.zoom).toHaveBeenCalledWith(1.3, undefined);
    expect(graphInstance.zoom).toHaveBeenCalledWith(0.77, undefined);
    expect(graphInstance.fitView).toHaveBeenCalledWith(300);
    expect(graphInstance.fitCenter).toHaveBeenCalledTimes(1);

    expect(container.firstChild).toHaveClass("graph-shell");
  });
});
