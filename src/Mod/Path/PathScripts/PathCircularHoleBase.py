# -*- coding: utf-8 -*-

# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2017 sliptonic <shopinthewoods@gmail.com>               *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

import ArchPanel
import FreeCAD
import DraftGeomUtils
import PathScripts.PathLog as PathLog
import PathScripts.PathOp as PathOp
import PathScripts.PathUtils as PathUtils
import string
import sys

from PySide import QtCore

__title__ = "Path Circular Holes Base Operation"
__author__ = "sliptonic (Brad Collette)"
__url__ = "http://www.freecadweb.org"
__doc__ = "Base class an implementation for operations on circular holes."

# Qt tanslation handling
def translate(context, text, disambig=None):
    return QtCore.QCoreApplication.translate(context, text, disambig)

if False:
    PathLog.setLevel(PathLog.Level.DEBUG, PathLog.thisModule())
    PathLog.trackModule(PathLog.thisModule())

class ObjectOp(PathOp.ObjectOp):
    '''Base class for proxy objects of all operations on circular holes.'''

    def opFeatures(self, obj):
        '''opFeatures(obj) ... calls circularHoleFeatures(obj) and ORs in the standard features required for processing circular holes.
        Do not overwrite, implement circularHoleFeatures(obj) instead'''
        return PathOp.FeatureTool | PathOp.FeatureDepths | PathOp.FeatureHeights | PathOp.FeatureBaseFaces | self.circularHoleFeatures(obj)

    def initOperation(self, obj):
        '''initOperation(obj) ... adds Disabled properties and calls initCircularHoleOperation(obj).
        Do not overwrite, implement initCircularHoleOperation(obj) instead.'''
        obj.addProperty("App::PropertyStringList", "Disabled", "Base", QtCore.QT_TRANSLATE_NOOP("Path", "List of disabled features"))
        self.initCircularHoleOperation(obj)

    def baseIsArchPanel(self, obj, base):
        '''baseIsArchPanel(obj, base) ... return true if op deals with an Arch.Panel.'''
        return hasattr(base, "Proxy") and isinstance(base.Proxy, ArchPanel.PanelSheet)

    def getArchPanelEdge(self, obj, base, sub):
        '''getArchPanelEdge(obj, base, sub) ... helper function to identify a specific edge of an Arch.Panel.
        Edges are identified by 3 numbers:
            <holeId>.<wireId>.<edgeId>
        Let's say the edge is specified as "3.2.7", then the 7th edge of the 2nd wire in the 3rd hole returned
        by the panel sheet is the edge returned.
        Obviously this is as fragile as can be, but currently the best we can do while the panel sheets
        hide the actual features from Path and they can't be referenced directly.
        '''
        ids = string.split(sub, '.')
        holeId = int(ids[0])
        wireId = int(ids[1])
        edgeId = int(ids[2])

        for holeNr, hole in enumerate(base.Proxy.getHoles(base, transform=True)):
            if holeNr == holeId:
                for wireNr, wire in enumerate(hole.Wires):
                    if wireNr == wireId:
                        for edgeNr, edge in enumerate(wire.Edges):
                            if edgeNr == edgeId:
                                return edge

    def holeDiameter(self, obj, base, sub):
        '''holeDiameter(obj, base, sub) ... returns the diameter of the specified hole.'''
        if self.baseIsArchPanel(obj, base):
            edge = self.getArchPanelEdge(obj, base, sub)
            return edge.BoundBox.XLength

        shape = base.Shape.getElement(sub)
        if shape.ShapeType == 'Vertex':
            return 0

        # for all other shapes the diameter is just the dimension in X
        return shape.BoundBox.XLength

    def holePosition(self, obj, base, sub):
        '''holePosition(obj, base, sub) ... returns a Vector for the position defined by the given features.
        Note that the value for Z is set to 0.'''
        if self.baseIsArchPanel(obj, base):
            edge = self.getArchPanelEdge(obj, base, sub)
            center = edge.Curve.Center
            return FreeCAD.Vector(center.x, center.y, 0)

        shape = base.Shape.getElement(sub)
        if shape.ShapeType == 'Vertex':
            return FreeCAD.Vector(shape.X, shape.Y, 0)

        if shape.ShapeType == 'Edge' and hasattr(shape.Curve, 'Center'):
            return FreeCAD.Vector(shape.Curve.Center.x, shape.Curve.Center.y, 0)

        if shape.ShapeType == 'Face' and hasattr(shape.Surface, 'Center'):
            return FreeCAD.Vector(shape.Surface.Center.x, shape.Surface.Center.y, 0)

        PathLog.error(translate("Path", "Feature %s.%s cannot be processed as a circular hole - please remove from Base geometry list.") % (base.Label, sub))
        return None

    def isHoleEnabled(self, obj, base, sub):
        '''isHoleEnabled(obj, base, sub) ... return true if hole is enabled.'''
        name = "%s.%s" % (base.Name, sub)
        return not name in obj.Disabled

    def opExecute(self, obj):
        '''opExecute(obj) ... processes all Base features and Locations and collects
        them in a list of positions and radii which is then passed to circularHoleExecute(obj, holes).
        If no Base geometries and no Locations are present, the job's Base is inspected and all
        drillable features are added to Base. In this case appropriate values for depths are also
        calculated and assigned.
        Do not overwrite, implement circularHoleExecute(obj, holes) instead.'''
        PathLog.track()

        def haveLocations(self, obj):
            if PathOp.FeatureLocations & self.opFeatures(obj):
                return len(obj.Locations) != 0
            return False

        if len(obj.Base) == 0 and not haveLocations(self, obj):
            # Arch PanelSheet
            features = []
            if self.baseIsArchPanel(obj, self.baseobject):
                holeshapes = self.baseobject.Proxy.getHoles(self.baseobject, transform=True)
                tooldiameter = obj.ToolController.Proxy.getTool(obj.ToolController).Diameter
                for holeNr, hole in enumerate(holeshapes):
                    PathLog.debug('Entering new HoleShape')
                    for wireNr, wire in enumerate(hole.Wires):
                        PathLog.debug('Entering new Wire')
                        for edgeNr, edge in enumerate(wire.Edges):
                            if PathUtils.isDrillable(self.baseobject, edge, tooldiameter):
                                PathLog.debug('Found drillable hole edges: {}'.format(edge))
                                features.append((self.baseobject, "%d.%d.%d" % (holeNr, wireNr, edgeNr)))

                self.setDepths(obj, None, None, self.baseobject.Shape.BoundBox)
            else:
                features = self.findHoles(obj, self.baseobject)
                self.setupDepthsFrom(obj, features, self.baseobject)
            obj.Base = features
            obj.Disabled = []

        holes = []

        for base, subs in obj.Base:
            for sub in subs:
                if self.isHoleEnabled(obj, base, sub):
                    pos = self.holePosition(obj, base, sub)
                    if pos:
                        holes.append({'x': pos.x, 'y': pos.y, 'r': self.holeDiameter(obj, base, sub)})
        if haveLocations(self, obj):
            for location in obj.Locations:
                holes.append({'x': location.x, 'y': location.y, 'r': 0})

        if len(holes) > 0:
            self.circularHoleExecute(obj, holes)

    def circularHoleExecute(self, obj, holes):
        '''circularHoleExecute(obj, holes) ... implement processing of holes.
        holes is a list of dictionaries with 'x', 'y' and 'r' specified for each hole.
        Note that for Vertexes, non-circular Edges and Locations r=0.
        Must be overwritten by subclasses.'''
        pass

    def opOnChanged(self, obj, prop):
        '''opOnChange(obj, prop) ... implements depth calculation if Base changes.
        Do not overwrite.'''
        if 'Base' == prop and not 'Restore' in obj.State and obj.Base:
            features = []
            for base, subs in obj.Base:
                for sub in subs:
                    features.append((base, sub))

            job = PathUtils.findParentJob(obj)
            if not job or not job.Base:
                return

            self.setupDepthsFrom(obj, features, job.Base)

    def setupDepthsFrom(self, obj, features, baseobject):
        '''setupDepthsFrom(obj, features, baseobject) ... determins the min and max Z values necessary.
        Note that the algorithm calculates "safe" values,
          it determines the highest top Z value of all features
          and it also determines the highest bottom Z value of all features.
        The result is that all features can be drilled safely and the operation
        does not drill deeper than any of the features requires.'''
        zmax = None
        zmin = None
        if not self.baseIsArchPanel(obj, baseobject):
            for base,sub in features:
                shape = base.Shape.getElement(sub)
                bb = shape.BoundBox
                # find the highes zmax and the highes zmin levels, those provide
                # the safest values for StartDepth and FinalDepth
                if zmax is None or zmax < bb.ZMax:
                    zmax = bb.ZMax
                if zmin is None or zmin < bb.ZMin:
                    zmin = bb.ZMin
        self.setDepths(obj, zmax, zmin, baseobject.Shape.BoundBox)

    def setDepths(self, obj, zmax, zmin, bb):
        '''setDepths(obj, zmax, zmin, bb) ... set properties according to the provided values.'''
        PathLog.track(obj.Label, zmax, zmin, bb)
        if zmax is None:
            zmax = bb.ZMax
        if zmin is None:
            zmin = bb.ZMin

        if zmin > zmax:
            zmax = zmin

        PathLog.debug("setDepths(%s): z=%.2f -> %.2f bb.z=%.2f -> %.2f" % (obj.Label, zmin, zmax, bb.ZMin, bb.ZMax))

        obj.StartDepth = zmax
        obj.ClearanceHeight = max(bb.ZMax, zmax) + 5.0
        obj.SafeHeight = max(bb.ZMax, zmax) + 3.0
        obj.FinalDepth = zmin

    def findHoles(self, obj, baseobject):
        '''findHoles(obj, baseobject) ... inspect baseobject and identify all features that resemble a straight cricular hole.'''
        shape = baseobject.Shape
        PathLog.track('obj: {} shape: {}'.format(obj, shape))
        holelist = []
        features = []
        # tooldiameter = obj.ToolController.Proxy.getTool(obj.ToolController).Diameter
        tooldiameter = None
        PathLog.debug('search for holes larger than tooldiameter: {}: '.format(tooldiameter))
        if DraftGeomUtils.isPlanar(shape):
            PathLog.debug("shape is planar")
            for i in range(len(shape.Edges)):
                candidateEdgeName = "Edge" + str(i + 1)
                e = shape.getElement(candidateEdgeName)
                if PathUtils.isDrillable(shape, e, tooldiameter):
                    PathLog.debug('edge candidate: {} (hash {})is drillable '.format(e, e.hashCode()))
                    x = e.Curve.Center.x
                    y = e.Curve.Center.y
                    diameter = e.BoundBox.XLength
                    holelist.append({'featureName': candidateEdgeName, 'feature': e, 'x': x, 'y': y, 'd': diameter, 'enabled': True})
                    features.append((baseobject, candidateEdgeName))
                    PathLog.debug("Found hole feature %s.%s" % (baseobject.Label, candidateEdgeName))
        else:
            PathLog.debug("shape is not planar")
            for i in range(len(shape.Faces)):
                candidateFaceName = "Face" + str(i + 1)
                f = shape.getElement(candidateFaceName)
                if PathUtils.isDrillable(shape, f, tooldiameter):
                    PathLog.debug('face candidate: {} is drillable '.format(f))
                    x = f.Surface.Center.x
                    y = f.Surface.Center.y
                    diameter = f.BoundBox.XLength
                    holelist.append({'featureName': candidateFaceName, 'feature': f, 'x': x, 'y': y, 'd': diameter, 'enabled': True})
                    features.append((baseobject, candidateFaceName))
                    PathLog.debug("Found hole feature %s.%s" % (baseobject.Label, candidateFaceName))

        PathLog.debug("holes found: {}".format(holelist))
        return features
