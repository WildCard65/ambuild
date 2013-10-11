# vim: set ts=8 sts=2 sw=2 tw=99 et:
#
# This file is part of AMBuild.
# 
# AMBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# AMBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with AMBuild. If not, see <http://www.gnu.org/licenses/>.
import os
import util
import nodetypes

class NodeBuilder(object):
  def __init__(self, type, path=None, folder=None, blob=None, generated=False):
    self.id = None
    self.type = type
    self.path = path
    self.folder = folder
    self.blob = blob
    self.generated = generated
    self.outgoing = set()
    self.incoming = set()

class GraphBuilder(object):
  def __init__(self):
    self.folders = {}
    self.files = {}
    self.commands = []
    self.edges = []

  def generateFolder(self, folder):
    if folder in self.folders:
      return self.folders[folder]

    if len(folder) == 0:
      # Don't create a node for the root folder.
      return None

    assert not os.path.isabs(folder)
    node = NodeBuilder(type=nodetypes.Mkdir, path=folder, generated=True)
    self.folders[folder] = node
    return node

  def addOutput(self, path):
    assert not os.path.isabs(path)
    assert not path in self.files

    node = NodeBuilder(type=nodetypes.Output, path=path)
    self.files[path] = node
    return node

  def addCommand(self, type, folder, path=None, data=None):
    assert folder is None or util.typeof(folder) is NodeBuilder

    node = NodeBuilder(type=type, path=path, folder=folder, blob=data)
    self.commands.append(node)
    return node

  def addDependency(self, outgoing, incoming):
    outgoing.incoming.add(incoming)
    incoming.outgoing.add(outgoing)
    self.edges.append((outgoing, incoming, False))

  def addSource(self, path):
    if path in self.files:
      return self.files[path]

    node = NodeBuilder(type=nodetypes.Source, path=path)
    self.files[path] = node
    return node