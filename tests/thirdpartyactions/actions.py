from zoidberg import actions


@actions.ActionRegistry.register('thirdpartyactions.AnExcellentAction')
class AnExcellentAction(actions.Action):
	def _do_run(self, *args, **kwargs):
		"""Mock third party action class for testing."""
