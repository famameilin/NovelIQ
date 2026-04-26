import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.cloud.schema import CloudAnalysis
from src.report.schema import ChartData, ChartSeries, DimensionSummary, ReportMeta, ReportPayload


class TestReportSchema(unittest.TestCase):
    def test_report_payload(self) -> None:
        meta = ReportMeta(novel_id="n1", title="书名", author="作者", genre="类型")
        dimensions = [
            DimensionSummary(name="叙事结构", metrics={"event_density": 0.5}, notes="ok"),
            DimensionSummary(name="情感曲线", metrics={"lexical_sentiment": 0.1}),
        ]
        charts = [
            ChartData(
                title="词汇情感密度",
                kind="line",
                series=[ChartSeries(name="pos-neg", x=[0.0, 1.0], y=[0.2, 0.1])],
            )
        ]
        cloud = CloudAnalysis(
            novel_id="n1",
            foreshadow_expectation=0.5,
            arc_scores=[0.2, 0.4],
            narrative_type="三幕",
            topic_labels=["成长"],
            diagnosis="ok",
        )
        report = ReportPayload(meta=meta, dimensions=dimensions, charts=charts, cloud_analysis=cloud)
        report.validate()
        payload = report.to_dict()
        self.assertEqual(payload["meta"]["title"], "书名")
        self.assertEqual(len(payload["dimensions"]), 2)
        self.assertEqual(payload["charts"][0]["series"][0]["name"], "pos-neg")


if __name__ == "__main__":
    unittest.main()
