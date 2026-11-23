"""Tests for improved progress reporting UI."""

from __future__ import annotations

from refactory.cli.ui.progress import loading, pipeline_progress


class TestLoading:
    def test_loading_context_manager(self):
        with loading("Testing..."):
            pass

    def test_loading_completes(self):
        done = False
        with loading("Working"):
            done = True
        assert done


class TestPipelineProgress:
    def test_creates_progress_bar(self):
        progress = pipeline_progress()
        assert progress is not None

    def test_progress_bar_has_columns(self):
        progress = pipeline_progress()
        assert len(progress.columns) > 0

    def test_progress_add_and_update_task(self):
        progress = pipeline_progress()
        with progress:
            task = progress.add_task("Parsing", total=10)
            progress.update(task, advance=5)
            assert progress.tasks[0].completed == 5

    def test_multiple_stages(self):
        progress = pipeline_progress()
        with progress:
            t1 = progress.add_task("Parsing", total=5)
            t2 = progress.add_task("Graph", total=3)
            progress.update(t1, completed=5)
            progress.update(t2, completed=3)
            assert progress.tasks[0].completed == 5
            assert progress.tasks[1].completed == 3
