import logging
import os
import re
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
        return self._actions.values()


class ActionValidationError(Exception):
    pass


class Action(object):
    def validate_config(self, cfg, cfg_block):
        if 'target' not in cfg_block:
            raise ActionValidationError(
                'No target found for %s action' % cfg_block['type'])
        if cfg_block['target'] not in cfg.gerrits.keys():
            raise ActionValidationError(
                'Target %s does not reference a gerrit instance'
                % cfg_block['target'])
        self._do_validate_config(cfg, cfg_block)

    def run(self, event, cfg, action_cfg, source):
        if 'branch_re' in action_cfg:
            branch = None
            if hasattr(event, 'change'):
                branch = event.change.branch
            elif hasattr(event, 'ref_update'):
                branch = event.ref_update.refname
            if not action_cfg['branch_re'].match(branch):
                return
        self._do_run(event, cfg, action_cfg, source)


class GitSshAction(Action):
    """Common code to run git+ssh commands."""
    def get_gerrit_credentials(self, source, target):
        """Generate a dict with user/key/host/port details."""
        data = {
            'source-username': source['username'],
            'source-host': source['host'],
            'source-port': source['port'],
            'target-username': target['username'],
            'target-host': target['host'],
            'target-port': target['port']
        }
        return data

    def make_ssh_wrapper(self, gerrit):
        filename = os.getcwd() + '/.tmp_ssh_' + gerrit['host']
        f = open(filename, 'w')
        f.write("""#!/bin/bash
        ssh -i %s $@
        """ % gerrit['key_filename'])
        f.close()
        st = os.stat(filename)
        os.chmod(filename, st.st_mode | stat.S_IEXEC)
        return filename

    def get_working_dir(self, gerrit, project):
        return '%s-%s-tmp' % (gerrit['host'],  project)

    def _run_cmd(self, cmd, ssh_wrapper):
        out, err = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            close_fds=True, env={'GIT_SSH': ssh_wrapper_filename}
        ).communicate()

        logging.debug(out)
        logging.debug(err)

    def git(self, git_command, gerrit, project, args=None, branch=None,
            working_dir=None, cleanup=False):
        """Wrapper around running git commands."""
        binary = '/usr/bin/git'
        git_ssh_url = 'ssh://%s@%s:%s/%s' % (
            gerrit['username'], gerrit['host'], gerrit['port'], project)
        if working_dir is None:
            working_dir = self.get_working_dir(gerrit, project)
        cmd = [binary, git_command, git_ssh_url]
        if git_command == 'clone':
            cmd_args.append(working_dir)
        if args is not None:
            cmd_args += args

        ssh_wrapper_filename = self.make_ssh_wrapper(gerrit)

        self._run_cmd(cmd, ssh_wrapper_filename)

        if git_command == 'clone':
            # only if we're cloning fresh, switch to the specified branch
            self._run_cmd(
                [binary, 'checkout', branch], ssh_wrapper_filename)
            self._run_cmd(
                [binary, 'pull'], ssh_wrapper_filename)

        if cleanup:
            self._run_cmd(['rm', '-rf', working_dir])


@ActionRegistry.register('zoidberg.SyncBranch')
class SyncBranchAction(GitSshAction):
    def _do_validate_config(self, cfg, cfg_block):
        return True

    def _do_run(self, event, cfg, action_cfg, source):
        target = cfg.gerrits[action_cfg['target']]
        branch = event.ref_update.refname
        project = event.ref_update.project

        self.git('clone', gerrit=source, project=project, branch=branch)

        self.git(
            'push', gerrit=target, project=project,
            args=['%s:refs/heads/%s' % (branch, branch), '--force'],
            cleanup=True, working_dir=self.get_working_dir(source))


@ActionRegistry.register('zoidberg.SyncReviewCode')
class SyncReviewCodeAction(GitSshAction):
    def _do_validate_config(self, cfg, cfg_block):
        return True

    def _do_run(self, event, cfg, action_cfg, source):
        target = cfg.gerrits[action_cfg['target']]
        branch = event.change.branch
        project = event.change.project
        ref = event.patchset.ref
        topic = event.change.topic

        # no easy way to do the sync through the gerrit client, so we put
        # together a short shell script to do it here.

        self.git('clone', gerrit=target, project=project, branch=branch)

        # fetch the ref submitted
        self.git('fetch', gerrit=source, project=project, args=[ref])

        # push FETCH_HEAD to the target gerrit and clean up
        self.git(
            'push', gerrit=target, project=project,
            args=['FETCH_HEAD:refs/for/%s/%s' % (branch, topic)],
            cleanup=True)


@ActionRegistry.register('zoidberg.PropagateComment')
class PropagateCommentAction(Action):

    def _do_validate_config(self, cfg, cfg_block):
        return True

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
        target_gerrit['client'].run_command(cmd)
