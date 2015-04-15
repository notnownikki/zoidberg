from zoidberg import actions


@actions.ActionRegistry.register('moreactions.JustSomeActionOrOther')
class AnExcellentAction(actions.Action):
	def _do_run(self, *args, **kwargs):
		"""Mock third party action class for testing."""
