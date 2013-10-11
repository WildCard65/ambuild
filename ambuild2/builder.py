# vim: set ts=8 sts=2 sw=2 tw=99 et:
import util, sys
import os, errno
import traceback
import nodetypes
from collections import deque
from task import Task, TaskMasterParent

# Given the partial command DAG, compute a task tree we can send to the task
# thread.
class TaskTreeBuilder(object):
  def __init__(self):
    self.worklist = []
    self.cache = {}
    self.cmd_list = []
    self.tree_leafs = []
    self.max_parallel = 0

  def buildFromGraph(self, graph):
    for node in graph.leaf_commands:
      leaf = self.enqueueCommand(node)
      self.tree_leafs.append(leaf)

    self.max_parallel = len(self.worklist)
    while len(self.worklist):
      task, node = self.worklist.pop()

      for outgoing in node.outgoing_cmds:
        outgoing_task = self.findTask(outgoing)
        task.addOutgoing(outgoing_task)

      if len(self.worklist) > self.max_parallel:
        self.max_parallel = len(self.worklist)

    return self.cmd_list, self.tree_leafs

  def findTask(self, node):
    if node in self.cache:
      return self.cache[node]
    return self.enqueueCommand(node)

  def enqueueCommand(self, node):
    assert node not in self.cache
    assert node.isCommand()
    outputs = [o.entry.path for o in node.outgoing if o.entry.type == nodetypes.Output]
    task = Task(len(self.cmd_list), node.entry, outputs)
    self.cache[node] = task
    self.cmd_list.append(node)
    self.worklist.append((task, node))
    return task

class Builder(object):
  def __init__(self, cx, graph):
    self.cx = cx
    self.graph = graph

    tb = TaskTreeBuilder()
    self.commands, self.leafs = tb.buildFromGraph(graph)
    self.max_parallel = tb.max_parallel

    # Set of nodes we'll mark as clean in the database.
    self.update_set = set()

  def printSteps(self):
    counter = 0
    leafs = deque(self.leafs)
    while len(leafs):
      leaf = leafs.popleft()
      print('task ' + str(format(counter)) + ': ' + leaf.format())
      for output in leaf.outputs:
        print('  -> ' + output)

      for child in leaf.outgoing:
        child.incoming.remove(leaf)
        if not len(child.incoming):
          leafs.append(child)

      counter += 1

  def update(self):
    tm = TaskMasterParent(self.cx, self, self.leafs, self.max_parallel)
    success = tm.run()
    self.commit()
    return success

  def findTask(self, task_id):
    return self.commands[task_id]

  def findPath(self, from_entry, to_entry):
    return False

  def lazyUpdateEntry(self, entry):
    assert entry.type == nodetypes.Source
    if entry.dirty:
      self.update_set.add(entry)

  def commit(self):
    # Update any dirty source file timestamps. It's important that files are
    # not modified in between being used as dependencies and the build
    # finishing; otherwise, the DAG state will be incoherent.
    for entry in self.update_set:
      self.cx.db.unmark_dirty(entry)
    self.cx.db.commit()

  def mergeDependencies(self, cmd_node, discovered):
    # Grab nodes for each dependency.
    discovered_set = set()
    for path in discovered:
      entry = self.cx.db.query_path(path)
      if not entry:
        if os.path.isabs(path):
          entry = self.cx.db.add_source(path)
        else:
          sys.stderr.write('Encountered an error while computing new dependencies:\n')
          sys.stderr.write('A new dependent file or path was discovered that has no corresponding build entry.\n')
          sys.stderr.write('This probably means a build script did not explicitly mark a generated file as an output.\n');
          sys.stderr.write('The build must abort since the ordering of these two steps is undefined.\n')
          sys.stderr.write('Path: {0}\n'.format(path))
          return False

      if entry.type != nodetypes.Source and entry.type != nodetypes.Output:
        sys.stderr.write('Fatal error in DAG construction!\n')
        sys.stderr.write('Dependent path {0} is not a file input!\n'.format(path))
        return False

      if entry.type == nodetypes.Output:
        if not self.findPath(entry, cmd_node.entry):
          sys.stderr.write('Encountered an error while computing new dependencies:\n')
          sys.stderr.write('A new dependency was discovered that exists as an output from another build step.\n')
          sys.stderr.write('However, there is no explicit dependency between that path and this command.\n')
          sys.stderr.write('The build must abort since the ordering of these two steps is undefined.\n')
          sys.stderr.write('Dependency: {0}\n'.format(path))
          return False

      discovered_set.add(entry)

    old_set = self.cx.db.query_incoming(cmd_node.entry)
    for entry in old_set:
      if not entry.generated:
        continue

      if entry not in discovered_set:
        self.cx.db.drop_edge(entry, cmd_node.entry)
      elif entry.type == nodetypes.Source:
        self.lazyUpdateEntry(entry)

    for entry in discovered_set:
      if entry in old_set:
        continue
      self.cx.db.add_edge(entry, cmd_node.entry, generated=True)
      if entry.type == nodetypes.Source:
        self.lazyUpdateEntry(entry)

    return True

  def updateGraph(self, node, updates, message):
    if 'deps' in message:
      if not self.mergeDependencies(node, message['deps']):
        return False

    return True