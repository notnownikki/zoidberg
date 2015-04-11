import configuration
import logging
import os
import stat
import subprocess


class ActionRegistry(object):
    """
    Easy lookup for action names to classes.
    """

    _actions = {}

    @classmethod
    def register(cls, name):
        def decorate(klazz):
            cls._actions[name] = klazz
            return klazz
        return decorate

    @classmethod
    def get(cls, name):
        return cls._actions.get(name)

    @classmethod
    def get_all(cls):
        return cls._actions.values()


class ActionValidationError(configuration.ValidationError):
    pass


class Action(object):

    def _do_startup(self, cfg, action_cfg, source, target):
        """
        Implement this method on your subclass if the action can also run
        as a startup task.

        cfg: the whole zoidberg configuration
        action_cfg: the action config dict
        source: config dict for the source gerrit
        target: config dict for the target gerrit
        """

    def _do_run(self, event, cfg, action_cfg, source):
        """
        Implement this method on your subclass.

        event: the event object from pygerrit
        cfg: the whole zoidberg configuration
        action_cfg: the action config dict
        source: config dict for the source gerrit
        """

    def _do_validate_config(self, cfg, cfg_block):
        """
        Implement this on your subclass if you have action specific
        configuration rules.

        Return True is the configuration is valid.
        """
        return True

    def validate_config(self, cfg, cfg_block):
        if 'target' not in cfg_block:
            # every action requires a target gerrit
            raise ActionValidationError(
                'No target found for %s action' % cfg_block['type'])

        if cfg_block['target'] not in cfg.gerrits.keys():
            # every target gerrit must exist in the configuration
            raise ActionValidationError(
                'Target %s does not reference a gerrit instance'
                % cfg_block['target'])
        self._do_validate_config(cfg, cfg_block)

    def startup(self, cfg, action_cfg, source):
        """
        Run as a startup task, when a connection is make to gerrit.

        Returns True if the target gerrit is online and action is run.
        """
        target = cfg.gerrits[action_cfg['target']]
        if not target['client'].is_active():
            return False

        if hasattr(self, '_do_startup'):
            self._do_startup(cfg, action_cfg, source, target)
            return True

        return False

    def run(self, event, cfg, action_cfg, source):
        """Run the action in response to an event."""
        if 'branch_re' in action_cfg:
            branch = None
            if hasattr(event, 'change'):
                branch = event.change.branch
            elif hasattr(event, 'ref_update'):
                branch = event.ref_update.refname

            if not action_cfg['branch_re'].match(branch):
                # not interested in events for this branch!
                return

        target_client = cfg.gerrits[action_cfg['target']]['client']
        if not target_client.is_active():
            # target gerrit isn't up, requeue the event
            source['client'].store_failed_event(event)
            return

        self._do_run(event, cfg, action_cfg, source)


class GitSshAction(Action):
    """Common code to run git+ssh commands."""
    def make_ssh_wrapper(self, gerrit):
        """
        Creates a shell script to wrap ssh with the gerrit key.

        Git doesn't have any way of telling it what ssh key to use,
        so we have to output a wrapper script around ssh and use the
        GIT_SSH environment variable to use the wrapper script.

        Returns the filename of the script.
        """
        filename = os.path.join(
            os.getcwd(), '.tmp_ssh_' + gerrit['host'])
        f = open(filename, 'w')
        f.write("""#!/bin/bash
        ssh -o StrictHostKeyChecking=no -i %s $@
        """ % gerrit['key_filename'])
        f.close()
        st = os.stat(filename)
        os.chmod(filename, st.st_mode | stat.S_IEXEC)
        return filename

    def get_working_dir(self, gerrit, project):
        """Returns the dir to work in for this gerrit/project repo."""
        return os.path.join(
            os.getcwd(), '%s-%s-tmp' % (gerrit['host'],  project))

    def _run_cmd(self, cmd, wdir, ssh_wrapper=''):
        out, err = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            close_fds=True, env={'GIT_SSH': ssh_wrapper},
            cwd=wdir).communicate()

        logging.debug(cmd)
        logging.debug(out)
        logging.debug(err)

    def git(self, git_command, gerrit, project, args=None, branch=None,
            working_dir=None, cleanup=False):
        """Wrapper around running git commands."""
        binary = '/usr/bin/git'
        git_ssh_url = 'ssh://%s@%s:%s/%s' % (
            gerrit['username'], gerrit['host'], gerrit['port'], project)

        if git_command == 'clone':
            # cloning repos is done inside the current zoidberg working dir
            working_dir = os.getcwd()
            # never cleanup when cloning
            cleanup = False

        if working_dir is None:
            # get the dir for the gerrit/project combo
            working_dir = self.get_working_dir(gerrit, project)

        cmd = [binary, git_command, git_ssh_url]

        if git_command == 'clone':
            # clone into the gerrit/project working dir
            cmd.append(self.get_working_dir(gerrit, project))

        if args is not None:
            # more args passed in by the caller
            cmd += args

        ssh_wrapper_filename = self.make_ssh_wrapper(gerrit)

        self._run_cmd(cmd, working_dir, ssh_wrapper_filename)

        if git_command == 'clone':
            # only if we're cloning fresh, switch to the specified branch
            # inside the gerrit/project working directory
            self._run_cmd(
                [binary, 'checkout', branch],
                self.get_working_dir(gerrit, project), ssh_wrapper_filename)
            self._run_cmd(
                [binary, 'pull'], self.get_working_dir(gerrit, project),
                ssh_wrapper_filename)

        if cleanup:
            self._run_cmd(['rm', '-rf', working_dir], working_dir)


@ActionRegistry.register('zoidberg.SyncBranch')
class SyncBranchAction(GitSshAction):
    def push_branch_to_target(self, source, target, project, branch):
        self.git('clone', gerrit=source, project=project, branch=branch)

        # working_dir is set explicitly here because we're working inside
        # a repo cloned from the source gerrit, but running a git command
        # targeted at the target gerrit
        self.git(
            'push', gerrit=target, project=project,
            args=['%s:refs/heads/%s' % (branch, branch), '--force'],
            cleanup=True, working_dir=self.get_working_dir(source, project))

    def _do_run(self, event, cfg, action_cfg, source):
        target = cfg.gerrits[action_cfg['target']]
        branch = event.ref_update.refname
        project = event.ref_update.project

        self.push_branch_to_target(source, target, project, branch)

    def _do_startup(self, cfg, action_cfg, source, target):
        projects = action_cfg['projects']
        branches = action_cfg['branches']
        for project in projects:
            for branch in branches:
                self.push_branch_to_target(source, target, project, branch)


@ActionRegistry.register('zoidberg.SyncReviewCode')
class SyncReviewCodeAction(GitSshAction):
    def _do_run(self, event, cfg, action_cfg, source):
        target = cfg.gerrits[action_cfg['target']]
        branch = event.change.branch
        project = event.change.project
        ref = event.patchset.ref
        topic = event.change.topic

        self.git(
            'clone', gerrit=source, project=project, branch=branch)

        # fetch the ref submitted
        self.git('fetch', gerrit=source, project=project, args=[ref])

        # push FETCH_HEAD to the target gerrit and clean up
        self.git(
            'push', gerrit=target, project=project,
            args=['FETCH_HEAD:refs/for/%s/%s' % (branch, topic)],
            cleanup=True, working_dir=self.get_working_dir(source, project))


@ActionRegistry.register('zoidberg.PropagateComment')
class PropagateCommentAction(Action):
    def _do_run(self, event, cfg, action_cfg, source):
        target_gerrit = cfg.gerrits[action_cfg['target']]
        commit = event.patchset.revision

        # construct the message header and look at the incoming
        # message for our propagation header structure
        incoming_comment_header = event.comment.split('\n')[0]
        user_header = '%s (%s)' % (event.author.name, event.author.email)
        message_header = '%s - (%s gerrit)' % (user_header, source['name'])
        if incoming_comment_header.startswith(user_header):
            if incoming_comment_header.endswith('gerrit)'):
                # don't repost if this is a propagated comment already
                return

        # prepare the message
        message = u'%s\n\n--------\n\n%s' % (message_header, event.comment)
        cmd = u'review %s -m "%s"' % (commit, message)
        # if the comment is for a change the target gerrit does not have,
        # gerrit will tell us that and we just carry on, because it's more
        # efficient to try to submit the comment and fail than to do another
        # gerrit call to see if the change exists and then do the comment
        # if it does
        target_gerrit['client'].run_command(cmd)
