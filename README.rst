Zoidberg - A Gerrit Event And Response Tool
===========================================

Zoidberg is a generic tool for easily running custom actions based
on gerrit events. Initially created to sync branches and reviews
between two master gerrits, where the code needed to be shared but
access had to be separate.

With zoidberg, you could...

- Notify an irc channel on an incoming review
- Sync merged code to a third party git repo
- ...respond to any gerrit event with anything you can implement in
  Python!

Setup and configuration
-----------------------

First, install the code:

    $> python setup.py install

Now create a configuration file with the details of your gerrit
servers, the events you want to respond to, and the actions to
carry out when those events happen.

The configuration file is in yaml format, so go ahead and create
an empty zoidberg.yaml, and we'll start putting in some details.

Configure gerrit instances
--------------------------

You'll need to tell zoidberg the details of the gerrits you're
dealing with. Zoidberg uses ssh to stream events from gerrit,
so you'll need an ssh key registered with your gerrit instance.

Here's how you configure a gerrit instance to connect to::

    - gerrits:
      - master:
          host: master-gerrit.yourdomain.com
          key_filename: /path/to/your/ssh_key
          username: your_username
          project-pattern: .*

``project-pattern`` is a regular expression that you can use to limit
the projects you're interested in. Events received for projects that
do not match this expression will be ignored.

You can configure multiple gerrit instances like this::

    - gerrits:
      - master:
          host: master-gerrit.yourdomain.com
          key_filename: /path/to/your/ssh_key
          username: your_username
          project-pattern: .*
      - third-party:
          host: gerrit.someone-else.com
          key_filename: /path/to/your/third_party_ssh_key
          username: your_username
          project-pattern: .*

Now when zoidberg starts up, it will connect to both gerrits and
start listening for events.

Configure actions
-----------------

When an event comes in that you're interested in, you will want to
respond with an action.

Example: when a comment is posted on a review on the ``master``
gerrit, we want it to be cross posted to the review for the same
change on the third-party gerrit.

Configuration::

    - gerrits:
      - master:
          host: master-gerrit.yourdomain.com
          key_filename: /path/to/your/ssh_key
          username: your_username
          project-pattern: .*
          events:
          - type: comment-added
            action: zoidberg.PropagateComment
            target: third-party
      - third-party:
          host: gerrit.someone-else.com
          key_filename: /path/to/your/third_party_ssh_key
          username: your_username
          project-pattern: .*

This will run the ``PropagateComment`` action with the third-party
gerrit as its target.

Zoidberg bundles some useful actions for you in zoidberg/actions.py

[TODO: developer guide for creating actions]

Configure startup tasks
-----------------------

If you're keeping code in sync from a master gerrit to a third-party,
you'll probably want to make sure everything is in sync when you
start up.

In zoidberg, actions can define a ``run`` method, which is used to
respond to events, and/or a ``startup`` method which is used when
zoidberg starts up. The bundled ``SyncBranch`` action implements both
and here's how you'd configure it to keep a third-party gerry in sync
with your master::

    - gerrits:
      - master:
          host: master-gerrit.yourdomain.com
          key_filename: /path/to/your/ssh_key
          username: your_username
          project-pattern: ^stuff$
          events:
          - type: ref-updated
            action: zoidberg.SyncBranch
            branch-pattern: ^master$
            target: third-party
          startup:
          - action: zoidberg.SyncBranch
            target: third-party
            projects: [stuff]
            branches: [master]
      - third-party:
          host: gerrit.someone-else.com
          key_filename: /path/to/your/third_party_ssh_key
          username: your_username
          project-pattern: .*

Here we're only interested in the ``stuff`` project on the master,
and when the master starts up we want to sync the ``master`` branch
on the ``stuff`` project over to the ``third-party`` gerrit.

The startup task configuration block is passed in to the action, so
any arguments extra to the required ``action`` and ``target``
(in this case, ``projects`` and ``branches``) will be accessible to
the action.

Run zoidberg
------------

  $> zoidberg-server -c /path/to/zoidberg.yaml

To run in debug mode and see a whole bunch output:

  $> zoidberg-server -c /path/to/zoidberg.yaml -v
