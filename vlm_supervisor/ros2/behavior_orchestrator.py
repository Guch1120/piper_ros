"""Behavior Orchestrator (ROS 2). Phase 6D 以降で実装する.

責務 (VLM 推論は行わない):
  start_behavior / interrupt_behavior / wait_until_stopped / start_recovery /
  finish_recovery / resume_behavior / force_transition / arbitrary_rejoin

利用予定の FlexBE interface (humble 2.3.x で存在を確認済み):
  flexbe/start_behavior (BehaviorSelection), flexbe/command/preempt (Empty),
  flexbe/command/pause / repeat / transition (OutcomeRequest), flexbe/status (BEStatus),
  flexbe/execute_behavior (BehaviorExecution action, flexbe_widget behavior_action_server)
"""


class BehaviorOrchestrator:
    def __init__(self, node):
        self.node = node

    def __getattr__(self, name):
        raise NotImplementedError(f"BehaviorOrchestrator.{name}: Phase 6D 以降で実装")
