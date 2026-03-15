import sys
from pathlib import Path
import tempfile
import unittest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.pipeline.pipeline import FileCache, MemoryCache, PipelineContext, Stage, run_pipeline


class TestPipeline(unittest.TestCase):
    def test_dependency_order(self) -> None:
        trace = []

        def make_handler(name: str):
            def handler(payload: dict, outputs: dict) -> str:
                trace.append(name)
                return name

            return handler

        stages = [
            Stage(name="a", handler=make_handler("a")),
            Stage(name="b", handler=make_handler("b"), dependencies=["a"]),
            Stage(name="c", handler=make_handler("c"), dependencies=["b"]),
        ]
        context = PipelineContext(payload={}, cache_key_base="t1")
        outputs = run_pipeline(stages, context)
        self.assertEqual(outputs["a"], "a")
        self.assertEqual(outputs["b"], "b")
        self.assertEqual(outputs["c"], "c")
        self.assertEqual(trace, ["a", "b", "c"])

    def test_memory_cache_skips(self) -> None:
        counter = {"x": 0}

        def handler(payload: dict, outputs: dict) -> int:
            counter["x"] += 1
            return counter["x"]

        stages = [Stage(name="x", handler=handler)]
        cache = MemoryCache()
        context = PipelineContext(payload={}, cache_key_base="t2")
        first = run_pipeline(stages, context, cache=cache)
        second = run_pipeline(stages, context, cache=cache)
        self.assertEqual(first["x"], 1)
        self.assertEqual(second["x"], 1)
        self.assertEqual(counter["x"], 1)

    def test_file_cache_persists(self) -> None:
        counter = {"x": 0}

        def handler(payload: dict, outputs: dict) -> int:
            counter["x"] += 1
            return counter["x"]

        stages = [Stage(name="x", handler=handler)]
        with tempfile.TemporaryDirectory() as tmp:
            cache = FileCache(Path(tmp) / "cache.json")
            context = PipelineContext(payload={}, cache_key_base="t3")
            first = run_pipeline(stages, context, cache=cache)
            second = run_pipeline(stages, context, cache=cache)
            self.assertEqual(first["x"], 1)
            self.assertEqual(second["x"], 1)
            self.assertEqual(counter["x"], 1)

    def test_rerun_stage(self) -> None:
        counter = {"x": 0}

        def handler(payload: dict, outputs: dict) -> int:
            counter["x"] += 1
            return counter["x"]

        stages = [Stage(name="x", handler=handler)]
        cache = MemoryCache()
        context = PipelineContext(payload={}, cache_key_base="t4")
        run_pipeline(stages, context, cache=cache)
        run_pipeline(stages, context, cache=cache, rerun_stages=["x"])
        self.assertEqual(counter["x"], 2)


if __name__ == "__main__":
    unittest.main()
