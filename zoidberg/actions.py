import logging
import os
import re
import stat


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


@ActionRegistry.register('zoidberg.EchoComment')
class EchoCommentAction(Action):
    def _do_validate_config(self, cfg, cfg_block):
        return True

    def _do_run(self, event, cfg, action_cfg, source):
        print event.comment


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


"""
{
    "type":"ref-updated",
    "submitter":{
        "name":"Nikki Heald",
        "email":"nicky@notnowlewis.com"
    },
    "refUpdate":{
        "oldRev":"a55b752df1b2c83a38c88ecb046dd1669a7a695e",
        "newRev":"ed06e568b2875dee876dea492a7decf0d48aa4e1",
        "refName":"master",
        "project":"nikki"
    }
}
{
    "type":"change-merged",
    "change":{
        "project":"nikki",
        "branch":"master",
        "topic":"woohoo",
        "id":"I54f9db5c9d3d3b2beaf1932fca22a9d808b46f15",
        "number":"8",
        "subject":"heeeeeeeeeeeloo",
        "owner":{
            "name":"Nikki Heald",
            "email":"nicky@notnowlewis.com"
        },
        "url":"http://10.0.3.38:8080/8"
    },
    "patchSet":{
        "number":"3",
        "revision":"ed06e568b2875dee876dea492a7decf0d48aa4e1",
        "ref":"refs/changes/08/8/3",
        "uploader":{
            "name":"Nikki Heald","email":"nicky@notnowlewis.com"
        },
        "createdOn":1427901393
    },
    "submitter":{
        "name":"Nikki Heald",
        "email":"nicky@notnowlewis.com"
    }
}
"""

@ActionRegistry.register('zoidberg.MarkChangeAsMerged')
class MarkChangeAsMergedAction(Action):
    pass


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

    def write_ssh_wrapper(self, data, template, filename):
        f = open(filename, 'w')
        f.write(template)
        f.close()
        st = os.stat(filename)
        os.chmod(filename, st.st_mode | stat.S_IEXEC)

    def run_git_ssh_script(self, script, data, target):
        """
        script must use GIT_SSH=%(ssh-script)s in front of any git commands.
        target is the config block for the gerrit we're interacting with.
        """
        cwd = os.getcwd()
        data['ssh-script'] = cwd + '/.tmp_ssh_' + target['host']

        # no way to pass the ssh key file to git commands! so we create
        # temporary wrapper files that inject it into the ssh command git uses
        git_ssh = """#!/bin/bash
        ssh -i %s $@
        """ % target['key_filename']
        self.write_ssh_wrapper(data, git_ssh, data['ssh-script'])
        print script % data
        # TODO: Popen and log output
        os.system(script % data)

    def clone_source_repo(self, data, source):
        """source is the config block of the source gerrit."""
        script = "GIT_SSH=%(ssh-script)s git clone "
        script += "ssh://%(source-username)s@%(source-host)s:%(source-port)s/"
        script += "%(project)s %(source-host)s-%(project)s-tmp; "
        self.run_git_ssh_script(script, data, source)
        

@ActionRegistry.register('zoidberg.SyncBranch')
class SyncBranchAction(GitSshAction):
    def _do_validate_config(self, cfg, cfg_block):
        return True

    def _do_run(self, event, cfg, action_cfg, source):
        target = cfg.gerrits[action_cfg['target']]
        data = self.get_gerrit_credentials(source, target)
        data['branch'] = event.ref_update.refname
        data['project'] = event.ref_update.project

        self.clone_source_repo(data, source)

        # check out the branch
        script = "cd %(source-host)s-%(project)s-tmp; "
        script += "GIT_SSH=%(ssh-script)s git checkout %(branch)s;"
        script += "GIT_SSH=%(ssh-script)s git pull;"
        self.run_git_ssh_script(script, data, source)

        # push to the target repo
        script = "cd %(source-host)s-%(project)s-tmp; "
        script += "GIT_SSH=%(ssh-script)s git push --force "
        script += "ssh://%(target-username)s@%(target-host)s:%(target-port)s/"
        script += "%(project)s %(branch)s:refs/heads/%(branch)s; "
        script += "cd ..; rm -rf %(source-host)s-%(project)s-tmp;"
        self.run_git_ssh_script(script, data, target)


@ActionRegistry.register('zoidberg.SyncReviewCode')
class SyncReviewCodeAction(GitSshAction):
    def _do_validate_config(self, cfg, cfg_block):
        return True

    def _do_run(self, event, cfg, action_cfg, source):
        target = cfg.gerrits[action_cfg['target']]
        data = self.get_gerrit_credentials(source, target)
        data['branch'] = event.change.branch
        data['project'] = event.change.project
        data['ref'] = event.patchset.ref
        data['topic'] = event.change.topic

        # no easy way to do the sync through the gerrit client, so we put
        # together a short shell script to do it here.

        self.clone_source_repo(data, source)

        # fetch the ref submitted
        script = "cd %(source-host)s-%(project)s-tmp; "
        script += "GIT_SSH=%(ssh-script)s git fetch "
        script += "ssh://%(source-username)s@%(source-host)s:%(source-port)s/"
        script += "%(project)s %(ref)s;"
        self.run_git_ssh_script(script, data, source)

        # push FETCH_HEAD to the target gerrit and clean up
        script = "cd %(source-host)s-%(project)s-tmp; "
        script += "GIT_SSH=%(ssh-script)s git push "
        script += "ssh://%(target-username)s@%(target-host)s:%(target-port)s/"
        script += "%(project)s FETCH_HEAD:refs/for/%(branch)s/%(topic)s; "
        script += "cd ..; rm -rf %(source-host)s-%(project)s-tmp;"
        self.run_git_ssh_script(script, data, target)
