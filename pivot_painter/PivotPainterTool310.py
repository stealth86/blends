# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
# 

bl_info = {
    "name": "Pivot Painter",
    "author": "George Vogiatzis (Gvgeo)",
    "version": (1, 1, 3),
    "blender": (3, 10, 0),
    "location": "View3D > Tool Shelf > Unreal Tools",
    "description": "Tools to create 3d model for Unreal Engine 4, that make use of the Pivot Painter Tool's material functions",
    "wiki_url": "https://github.com/Gvgeo/Pivot-Painter-for-Blender",
    "category": "Unreal Tools",
    }

import time, sys, math, ctypes, random, mathutils, bpy, os
import numpy as np
from ctypes import POINTER, pointer, c_int, cast, c_float
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import BoolProperty, PointerProperty, IntProperty, StringProperty
from math import floor, ceil, sqrt
from time import sleep

def progress(msg):																							# Progress for the system console 
	sys.stdout.write(msg + chr(8) * len(msg))
	sys.stdout.flush()
def complete(msg):																							# Progress for the system console when complete each process
	msg = msg + '\n'
	sys.stdout.write(msg)
	sys.stdout.flush()


def findTextureDimensions ():																				# Try to find efficient texture dimensions for the total number of object	
	ObjectToProcessCount = len(bpy.context.selected_objects)
	DecrementerTotal = 256 																					# 1600 had problems, problems. 256 is enough as it gives 64k pixel image.
	HalfEvenNumber = ((ObjectToProcessCount/2) % 2)
	HalfNumber = ceil(ObjectToProcessCount/2)
	modResult = 1
	if HalfNumber < DecrementerTotal :	# highest possible x dimension
		newDecrementerTotal = HalfNumber
	else:
		newDecrementerTotal = DecrementerTotal
	
	if HalfEvenNumber==0:
		decrementAmount = 2
	else:
		decrementAmount = 1
	
	complete = False
	while complete == False:			# tries to find y dimension by checking the mod=0 
		modResult = ObjectToProcessCount % newDecrementerTotal
		if modResult==0 or newDecrementerTotal < 1:
			complete = True
		if complete == False:
			newDecrementerTotal -= decrementAmount
		if newDecrementerTotal < 1:
			newDecrementerTotal=1
	
	if newDecrementerTotal == 1 or ((ObjectToProcessCount/newDecrementerTotal)>DecrementerTotal):
		Y = floor(sqrt(ObjectToProcessCount))
		X = ceil(ObjectToProcessCount/floor(Y))
		size=[X,Y]
	else:
		size=[newDecrementerTotal,(ObjectToProcessCount//newDecrementerTotal)]
		
	return size


def createUVMap(size,props): 																				# Create uvmap with point coordinates per object
	tt = time.time()
	for idx, obj in enumerate(bpy.context.selected_objects):
		progress("Create UV Map for object %i of %i" % (idx, len(bpy.context.selected_objects)))			# time is affected from vertex count mainly
		if props.automaticindexselect == True:
			obj.data.uv_layers.new(name = "PivotPainterMap") # it will not create if already 8 uvmap(max)
			layernumber = len(obj.data.uv_layers)-1 # will use the last layer
		else:
			layernumber = props.uvindex
			while len(obj.data.uv_layers) <= layernumber:			# Create enough layers to reach target
				obj.data.uv_layers.new(name = "PivotPainterMap") 
	
		x = idx%size[0]/size[0]+1/size[0] /2							# x and y, position of the object on the uv
		y = 1 - (floor(idx/size[0])/size[1]+1/size[1]/2) 				# y position inverted for consistency with UE4 Pivot Painter Shaders
		for poly in obj.data.polygons:
			for loopId in poly.loop_indices:								
				obj.data.uv_layers[layernumber].data[loopId].uv = (x, y)	# it sets all the vertices of the loop.
	complete("Create UV Map for object %i of %i, time %f" % (len(bpy.context.selected_objects), len(bpy.context.selected_objects), time.time()-tt))			# time is affected from vertex count mainly


def packTextureBits(index): 																				# Store Int to float 
	index = int(index)									# Not sure why is this necessary , and doesn't simply put the integer bits into the float directly. but it gets reverse in shader custom code. I include it for consistency, and ease of use.
	index = index +1024									# Need to check how the change from 32 float to 16(the exponent is the suspect) when saving affects the bits, if it does, probably the reason for this function. Otherwise I don't understand why cannot put int as float(and use 2^8 precision).
	sigh=index&0x8000
	sigh=sigh<<16
	exptest=index&0x7fff
	if exptest==0:
		exp=0
	else:
		exp=index>>10
		exp=exp&0x1f
		exp=exp-15
		exp=exp+127
		exp=exp<<23
	mant=index&0x3ff
	mant=mant<<13
	index=sigh|exp|mant
	
	cp = pointer(c_int(index))				# make this into a c integer				# cp points to the index (c_int conversion is needed from ctypes for pointere to work)
	fp = cast(cp, POINTER(c_float))			# cast the int pointer to a float pointer	# cast(obj, type) returns new instance that point to the same memory block, as type c_float by using POINTER(type)
	return fp.contents.value


def findrgbfunction(texturergb, hdr):																		# Select the rgb function
	if texturergb == 'PivotPoint' :	
		rgbfunction = pivotarray
		hdr = True						# For texture type
	elif texturergb == 'Xaxis' :
		rgbfunction = xaxisArray
	elif texturergb == 'Yaxis' :
		rgbfunction = yaxisArray
	elif texturergb == 'Zaxis' :
		rgbfunction = zaxisArray		
	elif texturergb == 'OriginPosition' :
		rgbfunction = originArray
		hdr = True
	elif texturergb == 'OriginExtents' :
		rgbfunction = ExtentsArray
		hdr = True
	else:
		rgbfunction = rgbnonefuction
	return rgbfunction, hdr


def findalphafunction(texturealpha, hdr):																	# Select the alpha function
	if texturealpha == 'Index' :		
		alphafunction = indexarray
		hdr = True
	elif texturealpha == 'Steps' or texturealpha == 'Hierarchyhdr':		#hierarchy is based on level function (later has a second process)
		alphafunction = level
		hdr = True
	elif texturealpha == 'Hierarchy' :
		alphafunction = level
	elif texturealpha == 'Randomhdr' :
		alphafunction = randomfloat
		hdr = True
	elif texturealpha == 'Diameter' :
		alphafunction = diagonal
		hdr = True
	elif texturealpha == 'Xextent' :
		alphafunction = xextent
	elif texturealpha == 'Yextent' :
		alphafunction = yextent
	elif texturealpha == 'Zextent' :
		alphafunction = zextent
	elif texturealpha == 'Random' :
		alphafunction = randomfloat										#the png stores alpha using 0-1 range while 0-256 rgb
	elif texturealpha == 'Diameterscaledhdr' :
		alphafunction = diagonalscaledhdr
		hdr = True
	elif texturealpha == 'Diameterscaled' :
		alphafunction = diagonalscaled
	elif texturealpha == 'SelectionOrder' :
		alphafunction = customorder
		hdr = True	
	elif texturealpha == 'Xwidth' :
		alphafunction = xextent
		hdr = True	
	elif texturealpha == 'Ydepth' :
		alphafunction = yextent
		hdr = True	
	elif texturealpha == 'Zheight' :
		alphafunction = zextent
		hdr = True	
	else: alphafunction = alphanonefuction
	return alphafunction, hdr


def texturefunction(pp, hdr, hdra, texturenubmer):															# Select function for each texture
	if texturenubmer == 0:																			# Select variables between the textures in the UIPanel
		texturergb = pp.rgb
		texturealpha = pp.alpha
	elif texturenubmer == 1: 
		texturergb = pp.rgb2
		texturealpha = pp.alpha2
	elif texturenubmer == 2: 
		texturergb = pp.rgb3
		texturealpha = pp.alpha3
	else:
		texturergb = pp.rgb4
		texturealpha = pp.alpha4
		
	rgbfunction, hdr = findrgbfunction(texturergb, hdr)												#Texture selection function for rgb pixels
	alphafunction, hdra = findalphafunction(texturealpha, hdra)
	
	if texturealpha == 'Randomhdr' :
		texturealpha = 'Random'
	elif texturealpha == 'Hierarchyhdr' :
		texturealpha = 'Hierarchy'
	elif texturealpha == 'Diameterscaledhdr' :
		texturealpha = 'DiameterScaled'
	return rgbfunction, alphafunction, texturergb, texturealpha, hdr, hdra							# should these values be global?


def createtexture(size,texturenubmer):																		# Create and save the textures
	pp = bpy.context.scene.pivot_painter
	pixels = [None] * size[0] * size[1] *4  																# RGB pixel list
	hdr = False																								# Bool for texture creation
	rgbfunction, alphafunction, texturergb, texturealpha, hdr, _ = texturefunction(pp, hdr, False,texturenubmer)	# Select variables between the textures in the UIPanel
	
	texturename = bpy.context.selected_objects[0].name + '_' + texturergb + '_' + texturealpha
	if hdr == True:
		texturename = texturename + '_HDR'
	if pp.createnew == False:																		#check if there is already the texture, else create new.
		for img in bpy.data.images:
			if img.name == texturename:
				image = img
				bpy.data.images.remove(image)														# there is no way to change dimensions
	image = bpy.data.images.new(name=texturename, width=size[0], height=size[1], float_buffer=hdr)
	
	pixels = setpixels(rgbfunction, alphafunction, texturealpha, texturenubmer, pp, size, pixels, hdr)	# Calculate the pixels values
	image.pixels = pixels																			# assign pixels

	if pp.savetextures == True:	
		image_settings = bpy.context.scene.render.image_settings
		image_settings.color_mode = 'RGBA'
		if hdr == True:
			imagepath = bpy.path.abspath(pp.folderpath) + image.name +'.exr'			
			image_settings.file_format = 'OPEN_EXR'
			image_settings.color_depth = '16'
		else:
			imagepath = bpy.path.abspath(pp.folderpath) + image.name +'.png'
			image_settings.file_format = 'PNG'
			image_settings.color_depth = '8'
		image.save_render(imagepath)


def setpixels(rgbfunction, alphafunction, texturealpha, texturenubmer, pp, size, pixels, hdr):				# Calculate the pixels values
	counter = 0
	tt = time.time()
	for obj in bpy.context.selected_objects:							# The 
		rgbvalues = rgbfunction(pp, obj, counter, size, pixels, hdr)			# Does sending unused values affect performance(even if minimal)?  There must be a better way. (with the function selection)
		alphavalue = alphafunction(pp, obj, counter, size, pixels, hdr)
		pixelindex=((size[0]*size[1])-((floor(counter/size[0])+1)*size[0])+(counter%size[0]))
		pixels[pixelindex*4] = rgbvalues[0]		
		pixels[pixelindex*4+1] = rgbvalues[1]
		pixels[pixelindex*4+2] = rgbvalues[2]		
		pixels[pixelindex*4+3] = alphavalue
		progress("Calculating pixel %i of %i for texture %i" % (counter, len(bpy.context.selected_objects), texturenubmer +1 ))
		counter = counter + 1

	foundthem = False											# Only a couple pixels should be empty near the start.
	for i in range(len(pixels)):								# Fill Empty pixels
		if pixels[i] == None:
			pixels[i] = 1
			foundthem =True
		elif foundthem ==True:									# if have found empty pixels, but not anymore empty, stop.
			break
	if texturealpha == 'Hierarchy':	# second part of the function to create the hierarchy
		pixels = hierarchy(pp, obj, counter, size, pixels, hdr)
	complete("Calculating pixel %i of %i for texture %i, time %f" % (len(bpy.context.selected_objects), len(bpy.context.selected_objects), texturenubmer +1, time.time()-tt))
	return pixels


def rgbnonefuction(pp, obj, counter, size, pixels, hdr):													# 0 as rgb values , to avoid Null problems (used at the end to fill empty pixels)
	rgb = ( 0, 0, 0)
	return rgb


def alphanonefuction(pp, obj, counter, size, pixels, hdr):													# 0 as alpha, to avoid Null problems (used at the end to fill empty pixels)
	a = 0
	return a


def hierarchy(pp, obj, counter, size, pixels, hdr):															# Hierarchy, current level of the object / highest possible level
	maxlevel = 1
	for i in range(3,len(pixels),4):
		currentlevel = pixels[i]
		if currentlevel > maxlevel:
			maxlevel = currentlevel
	print ('Max level is ', maxlevel)
	for i in range(3,len(pixels),4):
		currentlevel = pixels[i]
		normalizedlevel = currentlevel / maxlevel
		pixels[i] = normalizedlevel
	return pixels


def customorder(pp, obj, counter, size, pixels, hdr):														# Selection order using custom property
	a = obj["SelectionOrder"]
	a = packTextureBits(a)
	return a


def diagonal(pp, obj, counter, size, pixels, hdr):															# Diagonal length of the bound box
	vec1= mathutils.Vector ((obj.bound_box[0][0], obj.bound_box[0][1], obj.bound_box[0][2] ))				# Vector from the origin point to the min vertex position of the boundbox, unscaled
	vec2= mathutils.Vector ((obj.bound_box[6][0], obj.bound_box[6][1], obj.bound_box[6][2] ))				# Max vertex is 6 (lists start from zero, six is the seventh item in a list)
	diagonalvector = vec1 - vec2																			# Vectors point to the opposite direction
	length = diagonalvector.length
	return length


def diagonalscaledhdr(pp, obj, counter, size, pixels, hdr):													# Diagonal length of the bound box scaled
	ws=obj.matrix_world.to_scale()																							# The scale of the object
	vec1= mathutils.Vector ((obj.bound_box[0][0] * ws[0], obj.bound_box[0][1] * ws[1], obj.bound_box[0][2] * ws[2] ))       # Vector from the origin point to the min vertex position of the boundbox, scaled
	vec2= mathutils.Vector ((obj.bound_box[6][0] * ws[0], obj.bound_box[6][1] * ws[1], obj.bound_box[6][2] * ws[2] ))		# Max vertex is 6
	diagonalvector = vec1 - vec2
	length = diagonalvector.length
	return length


def diagonalscaled(pp, obj, counter, size, pixels, hdr):													# Diagonal length of the bound box scaled
	ws=obj.matrix_world.to_scale()																							# The scale of the object
	vec1= mathutils.Vector ((obj.bound_box[0][0] * ws[0], obj.bound_box[0][1] * ws[1], obj.bound_box[0][2] * ws[2] ))       # Vector from the origin point to the min vertex position of the boundbox, scaled
	vec2= mathutils.Vector ((obj.bound_box[6][0] * ws[0], obj.bound_box[6][1] * ws[1], obj.bound_box[6][2] * ws[2] ))		# Max vertex is 6
	diagonalvector = vec1 - vec2
	length = diagonalvector.length
	length = length /8 			
	length = np.clip(length,1,256)
	length = length /256
	return length


def randomfloat(pp, obj, counter, size, pixels, hdr):														# Random float
	a = random.random()
	return a


def ExtentsArray(pp, obj, counter, size, pixels, hdr):														# Extents(Dimensions) in local coordinates
	r = obj.dimensions[0]
	g = obj.dimensions[1]
	b = obj.dimensions[2]
	rgbvalues = [ r, g, b, ]
	return rgbvalues


def originArray(pp, obj, counter, size, pixels, hdr):														# Find the center of the boundbox. Origin Position (not Pivot Point)
	ws=obj.matrix_world.to_scale()																							# The scale of the object
	vec1= mathutils.Vector ((obj.bound_box[0][0] * ws[0], obj.bound_box[0][1] * ws[1], obj.bound_box[0][2] * ws[2] ))       # Vector from the origin point to the min vertex position of the boundbox, scaled
	vec2= mathutils.Vector ((obj.bound_box[6][0] * ws[0], obj.bound_box[6][1] * ws[1], obj.bound_box[6][2] * ws[2] ))		# Max vertex is 6
	center = vec1 + vec2
	center = center /2							# Vector point to Center of the boundbox from origin point in local coordinates

	wr=obj.matrix_world.to_euler('XYZ')			# Rotation of the obj
	center.rotate(wr)
	wl=obj.matrix_world.to_translation()		# Origin position in global coordinates
	center = center + wl						# The boundbox center in global coordinates
	r = center[0]
	g = center[1]
	b = center[2]
	rgbvalues = [ r, g, b, ]
	return rgbvalues																		# TO DO(Canceled, it cannot be used with the current shaders): use 3cursor move technic so I can set center type, mass or bb or surface center.


def indexarray(pp, obj, counter, size, pixels, hdr):														# Index of the parent. (Used to inherit properties, like rotation position.)
	if obj.parent:
		index=float(bpy.context.selected_objects.index(obj.parent)) 	# index nubmer of the parent. # do I need remove .5 ? In find object parents it removes from arrayIndex (Line1113 at PivotPainter2.ms)# YES SEE "2dArrayLookupByIndex" material function in the unreal engine. it adds .5 # NO. TESTED. the index wont work.
	else:
		index=float(bpy.context.selected_objects.index(obj))
	#index = index - 0.5																					# NO FAILURE # Testing # For compatibility function to be the same as the maxscript. (I have no Idea why this operation ) 
	a = packTextureBits(index)										# packs int to float
	return a


def level(pp, obj, counter, size, pixels, hdr):																# Level, number of parents of every object.
	par=[] 											# Create a list with the parents of the obj
	j = 0
	if obj.parent:
		par.append(obj.parent) 						# First input for while loop. without the first it fails.
		while par[j].parent: 						# IF the parent has a parent    (can it be simplified?)
			par.append(par[j].parent)				# add it to the list
			j=j+1
	level = len(par)
	return level


def pivotarray(pp, obj, counter, size, pixels, hdr): 														# Pivot point, in practice the origin position.
	wl=obj.matrix_world.to_translation()		# Gives world location
	r=wl[0]*100
	g=-wl[1]*100
	b=wl[2]*100
	rgbvalues = [ r, g, b, ]
	return rgbvalues


def boundboxAxis(pp, obj, counter, size, pixels, hdr):														# Estimates the X vector from the origin point and boundbox vertices. Works only when object has zero rotation.
	bbvv=[None for x in range(8)]
	bbLength=[None for x in range(8)]	
	ws=obj.matrix_world.to_scale()
	for i in range(8):
		bbvv[i] = mathutils.Vector((obj.bound_box[i][0] * ws[0], obj.bound_box[i][1] * ws[1], obj.bound_box[i][2] * ws[2] ))	# Create a vector list for each vert of the bounding box (from origin point)
		bbLength[i] = bbvv[i].length						# Create list with the lengths
		
	# Find the furthest points from origin (Hopefully they are near the main direction of the object, to use as a xaxis)
	highestVertexId = 0
	for i in range(1,8):										# find the furthest point
		if bbLength[highestVertexId] < bbLength[i]:
			highestVertexId = i
	
	fvidlist = []
	for i in range(8):																						# Check if other vertex have roughly the same distance
		if bbLength[i] >= ( bbLength[highestVertexId] * pp.percentagefreedom / 100 ):			# Give a small range to include points with similar distances from the origin point, Blender inconsistencies(from floating values?) and users input
			fvidlist.append(i)

	# Get an average position
	axisdir = mathutils.Vector((0.0, 0.0, 0.0))
	for i in range(len(fvidlist)):
		axisdir = bbvv[fvidlist[i]] + axisdir
	axisdir = axisdir /len(fvidlist)
	
	vecout=axisdir.normalized()
	axisextent = axisdir.length
	return vecout, axisextent


def xaxisArray(pp, obj, counter, size, pixels, hdr):														# X Axis, the direction of the local x axis	
	if pp.firstlevel == True or pp.secondlevel == True or pp.thirdlevel == True or pp.fourthlevel == True :				# Avoid unnecessary calculations. Probably wont use BoundBox method
		localevel = 0
		localevel = level (pp, obj, counter, size, pixels, hdr)
		if (localevel == 0 and pp.firstlevel == True) or (localevel == 1 and pp.secondlevel == True) or (localevel == 2 and pp.thirdlevel == True) or (localevel == 3 and pp.fourthlevel == True) :		# Choosing BoundBox method 
			vec, _ = boundboxAxis(pp, obj, counter, size, pixels, hdr)
		else:
			vec = mathutils.Vector((1.0, 0.0, 0.0))
			wr=obj.matrix_world.to_euler('XYZ')
			vec.rotate(wr)	
	else:
		vec = mathutils.Vector((1.0, 0.0, 0.0))
		wr=obj.matrix_world.to_euler('XYZ')
		vec.rotate(wr)
	r = ( vec[0] +1 ) /2
	g = ( (-vec[1]) +1 ) /2
	b = ( vec[2] +1 ) /2
	rgbvalues = [r, g, b]
	return rgbvalues

def yaxisArray(pp, obj, counter, size, pixels, hdr):														# Y Axis, the direction of the local Y axis 
	vec = mathutils.Vector((0.0, 1.0, 0.0))
	wr=obj.matrix_world.to_euler('XYZ')
	vec.rotate(wr)
	r = ( vec[0] +1 ) /2
	g = ( (-vec[1]) +1 ) /2
	b = ( vec[2] +1 ) /2
	rgbvalues = [r, g, b]
	return rgbvalues

def zaxisArray(pp, obj, counter, size, pixels, hdr):														# Z Axis, the direction of the local z axis
	vec = mathutils.Vector((0.0, 0.0, 1.0))
	wr=obj.matrix_world.to_euler('XYZ')
	vec.rotate(wr)
	r = ( vec[0] +1 ) /2
	g = ( (-vec[1]) +1 ) /2
	b = ( vec[2] +1 ) /2
	rgbvalues = [r, g, b]
	return rgbvalues

def xextent(pp, obj, counter, size, pixels, hdr):															# X Extent, the length of the object on the local x axis
	if pp.firstlevel == True or pp.secondlevel == True or pp.thirdlevel == True or pp.fourthlevel == True :				# Avoid unnecessary calculations. Probably wont use BoundBox method
		localevel = 0
		localevel = level (pp, obj, counter, size, pixels, hdr)
		if (localevel == 0 and pp.firstlevel == True) or (localevel == 1 and pp.secondlevel == True) or (localevel == 2 and pp.thirdlevel == True) or (localevel == 3 and pp.fourthlevel == True) :		# Choosing BoundBox method 
			_, a = boundboxAxis(pp, obj, counter, size, pixels, hdr)
			a = a*100/8
		else:
			a = obj.dimensions[0]*100/8 
	else:
		a = obj.dimensions[0]*100/8 			# "Dimensions" property, change with the scale -> There is no need to apply scale, nor does it effect it.
	if hdr == False :
		a = np.clip(a,1,256)
		a = a /256
	return a

def yextent(pp, obj, counter, size, pixels, hdr):															# Y Extent, the length of the object on the local y axis
	a = obj.dimensions[1]/8 			# "Dimensions" property, change with the scale -> There is no need to apply scale, nor does it effect it.
	if hdr == False :
		a = np.clip(a,1,256)
		a = a /256
	return a

def zextent(pp, obj, counter, size, pixels, hdr):															# Z Extent, the length of the object on the local z axis
	a = obj.dimensions[2]/8 			# "Dimensions" property, change with the scale -> There is no need to apply scale, nor does it effect it.
	if hdr == False :
		a = np.clip(a,1,256)
		a = a /256
	return a


class UE4_PivotPainterProperties(PropertyGroup):															# create property group for user options
	
	alpha_options = [
		("Index", "HDR - Parent Index", 'The index number of each part.\n\nIf save texture manually, save as OpenEXR, RGBA, Color Depth:Float(Half).'),
		("Steps", "HDR - Number of Steps From Root", 'The level in the hierarchy.\n\nIf save texture manually, save as OpenEXR, RGBA, Color Depth:Float(Half).'),
		("Randomhdr", "HDR - Random 0-1 Value Per Element", 'Creates a random number per object.\n\nIf save texture manually, save as OpenEXR, RGBA, Color Depth:Float(Half).'),
		("Diameter", "HDR - Bounding Box Diameter", 'The length of the diagonal of the bound box before scale.\n\nIf save texture manually, save as OpenEXR, RGBA, Color Depth:Float(Half).'),
		("SelectionOrder", "HDR - Selection Order", 'First create selection order from the extra options.\nAfter you create the order, you can change it.\nYou can also set more objects on the same number,\nor skip numbers to create empty time in the animation.\n\n\nIf save texture manually, save as OpenEXR, RGBA, Color Depth:Float(Half).'),
		("Hierarchyhdr", "HDR - Normalized 0-1 Hierarchy Position", 'Object number/ Total nubmer of objects.\n\nIf save texture manually, save as OpenEXR, RGBA, Color Depth:Float(Half).'),
		("Xwidth", "HDR - Object X Width", 'The extent of each object on its local X axis.\nValue source is the X Dimension.\n\nIf save texture manually, save as OpenEXR, RGBA, Color Depth:Float(Half).'),
		("Ydepth", "HDR - Object Y Depth", 'The extent of each object on its local Y axis.\nValue source is the Y Dimension.\n\nIf save texture manually, save as OpenEXR, RGBA, Color Depth:Float(Half).'),
		("Zheight", "HDR - Object Z Height", 'The extent of each object on its local Z axis.\nValue source is the Z Dimension.\n\nIf save texture manually, save as OpenEXR, RGBA, Color Depth:Float(Half).'),
		("Hierarchy", "Normalized 0-1 Hierarchy Position", 'Object number/ Total nubmer of objects.\n\nIf save texture manually, save as PNG, RGBA, Color Depth:8'),
		("Random", "Random 0-1 Value Per Element", 'Creates a random number per object.\n\nIf save texture manually, save as PNG, RGBA, Color Depth:8'),
		("Xextent", "X extent", 'The extent of each object on its local X axis.\nValue source is the X Dimension.\nValues between 8-2048 in increments of 8.\n\nIf save texture manually, save as PNG, RGBA, Color Depth:8'),
		("Yextent", "Y extent", 'The extent of each object on its local Y axis.\nValue source is the Y Dimension.\nValues between 8-2048 in increments of 8.\n\nIf save texture manually, save as PNG, RGBA, Color Depth:8'),
		("Zextent", "Z extent", 'The extent of each object on its local Z axis.\nValue source is the Z Dimension.\nValues between 8-2048 in increments of 8.\n\nIf save texture manually, save as PNG, RGBA, Color Depth:8'),
		("Diameterscaledhdr", "HDR - Scaled Bounding Box Diameter", 'The length of the diagonal of the bound box WITH scale taken into calculation.\n\nIf save texture manually, save as OpenEXR, RGBA, Color Depth:Float(Half).'),
		("Diameterscaled", "Scaled Bounding Box Diameter", 'The length of the diagonal of the bound box WITH scale taken into calculation\nValues between 8-2048 in increments of 8.\n\nIf save texture manually, save as PNG, RGBA, Color Depth:8'),
		("None", "None", 'Will use as alpha value 0')
	]
	rgb_options = [
		("PivotPoint", "Pivot Point HDR", 'The origin point of each object.\n\nIf save texture manually, save as OpenEXR, RGBA, Color Depth:Float(Half).'),
		("OriginPosition", "Origin Position HDR", 'The bound box center of each object.\n\nIf save texture manually, save as OpenEXR, RGBA, Color Depth:Float(Half).'),
		("OriginExtents", "Origin Extents HDR", 'The maximum length of every local axis of each object\nValues source are the object Dimensions.\n\nIf save texture manually, save as OpenEXR, RGBA, Color Depth:Float(Half).'),
		("Xaxis", "X Axis", 'X Axis from rotation.\n\nIf save texture manually, save as PNG, RGBA, Color Depth:8.'),
		("Yaxis", "Y Axis", 'Y Axis from rotation.\n\nIf save texture manually, save as PNG, RGBA, Color Depth:8'),
		("Zaxis", "Z Axis", 'Z Axis from rotation.\n\nIf save texture manually, save as PNG, RGBA, Color Depth:8'),
		("None", "None", 'Will use as rgb values 0')
	]
	rgb : bpy.props.EnumProperty( items=rgb_options, name="RGB", description= "When you save textures manually,\nIf HDR texture save as OpenEXR, RGBA, Color Depth:Float(Half)\nelse use PNG, RGBA, Color Depth:8\n\nCurrent", default="PivotPoint") # Any other way to create multiple of them in loop? And display on the UI.
	alpha : bpy.props.EnumProperty( items=alpha_options, name="Alpha", description = "When you save textures manually,\nIf HDR texture save as OpenEXR, RGBA, Color Depth:Float(Half)\nelse use PNG, RGBA, Color Depth:8\n\nCurrent", default="Index" )
	rgb2 : bpy.props.EnumProperty( items=rgb_options, name="RGB", description= "When you save textures manually,\nIf HDR texture save as OpenEXR, RGBA, Color Depth:Float(Half)\nelse use PNG, RGBA, Color Depth:8\n\nCurrent", default="Xaxis" )
	alpha2 : bpy.props.EnumProperty( items=alpha_options, name="Alpha", description = "When you save textures manually,\nIf HDR texture save as OpenEXR, RGBA, Color Depth:Float(Half)\nelse use PNG, RGBA, Color Depth:8\n\nCurrent", default="Xextent")
	rgb3 : bpy.props.EnumProperty( items=rgb_options, name="RGB", description= "When you save textures manually,\nIf HDR texture save as OpenEXR, RGBA, Color Depth:Float(Half)\nelse use PNG, RGBA, Color Depth:8\n\nCurrent", default="OriginPosition" )
	alpha3 : bpy.props.EnumProperty( items=alpha_options, name="Alpha", description = "When you save textures manually,\nIf HDR texture save as OpenEXR, RGBA, Color Depth:Float(Half)\nelse use PNG, RGBA, Color Depth:8\n\nCurrent", default="SelectionOrder")
	rgb4 : bpy.props.EnumProperty( items=rgb_options, name="RGB", description= "When you save textures manually,\nIf HDR texture save as OpenEXR, RGBA, Color Depth:Float(Half)\nelse use PNG, RGBA, Color Depth:8\n\nCurrent", default="OriginExtents" )
	alpha4 : bpy.props.EnumProperty( items=alpha_options, name="Alpha", description = "When you save textures manually,\nIf HDR texture save as OpenEXR, RGBA, Color Depth:Float(Half)\nelse use PNG, RGBA, Color Depth:8\n\nCurrent", default="Hierarchyhdr")
	
	automaticindexselect : BoolProperty(name = "Auto UVindex", description = ("Creates a new UVMap.\nIf there are already 8 UVMaps, will rewrite the last one.\nDefault DISABLED with UVIndex 1. "))
	uvindex : IntProperty( name="UVIndex", description="UVindex to store the textures coordinates.\nThe Unreal Engine Pivot Painter Tool 2 shaders use UV index 1 by default.\nWill create enough UV maps to reach target. ", default=1,	min=0, max=7)	
	
	extraoptions : BoolProperty( name = "Extra options", default = False)
	experimentaloptions : BoolProperty( name = "Experimental options", default = False)
	totaltextures : IntProperty( name = "Number of Textures", description = "Number of textures to be created. ", default = 2, min = 0, max = 4)

	firstlevel : bpy.props.BoolProperty(name = "1st", description = "For Use with objects that have 0 rotation.\nCalculate the X Axis properties from the BoundBox for the first level.\nOutcome is not very accurate, but should be sufficient.\nVector from origin point and the furthest vertices of the boundingbox.\nWill not work for Y,Z Axes")
	secondlevel : bpy.props.BoolProperty(name = "2nd", description = "For Use with objects that have 0 rotation.\nCalculate the X Axis properties from the BoundBox for the second level.\nOutcome is not very accurate, but should be sufficient.\nVector from origin point and the furthest vertices of the boundingbox.\nWill not work for Y,Z Axes")
	thirdlevel : bpy.props.BoolProperty(name = "3rd", description = "For Use with objects that have 0 rotation.\nCalculate the X Axis properties from the BoundBox for the third level.\nOutcome is not very accurate, but should be sufficient.\nVector from origin point and the furthest vertices of the boundingbox.\nWill not work for Y,Z Axes")
	fourthlevel : bpy.props.BoolProperty(name = "4th", description = "For Use with objects that have 0 rotation.\nCalculate the X Axis properties from the BoundBox for the fourth level.\nOutcome is not very accurate, but should be sufficient.\nVector from origin point and the furthest vertices of the boundingbox.\nWill not work for Y,Z Axes")
	percentagefreedom : bpy.props.FloatProperty( name="BoundBox Percentage", description="Finds the distance of the furthest vertex of the boundingbox from the origin point.\nThen includes other vertexes that have distance bigger than the percentage given, and estimates an average point to approximate X axis and extent.\nIn almost all cases the default value is strongly advised.\nDefault 90%", default=90,soft_min=50, min=50, max=99.9999, soft_max=99 )

	selectingobjects : BoolProperty( name = "Selecting Objects", default = False, description = ("Press Again to confirm selection, or ESC to cancel.\n\nYou can select more than 1 object each time. "))	
	orderstart : IntProperty( name="Order Start Number", description="The number the order count should start.\nDefault 1", default=1, min=1, soft_max=100, max=30000)	
	dontcount : BoolProperty( name = "Same order number", default = False, description = ("Create the same order number for all selected objects"))	

	savetextures : BoolProperty( name = "Save Textures to folder", default = False, description = ("Will always OVERWRITE texture files with the same name\n\nSave textures to the specified folder location"))
	folderpath : StringProperty( name = "Save location", description="Choose a directory:", default='', maxlen=1024, subtype='DIR_PATH')
	createnew : BoolProperty( name = "Always create new textures", default = True, description = ("Should it create a new texture or use the first one?"))


def main(context):																							# The start of all the problems
	print('===================')
	print('Pivot Painter start')
	tt = time.time()
	pp = context.scene.pivot_painter 

	if pp.totaltextures>=1 :	
		size = findTextureDimensions()
		createUVMap(size,pp)
		if (pp.rgb != 'None' or pp.alpha != 'None' ) :
			createtexture(size, 0)													# Start the texture creation for each one set
		if pp.totaltextures>=2 and (pp.rgb2 != 'None' or pp.alpha2 != 'None') :
			createtexture(size, 1)
		if pp.totaltextures>=3 and (pp.rgb3 != 'None' or pp.alpha3 != 'None') :
			createtexture(size, 2)
		if pp.totaltextures==4 and (pp.rgb4 != 'None' or pp.alpha4 != 'None') :
			createtexture(size, 3)	


class PPB_OT_ShowHideExtraOptions(Operator):																		# Extra options toggle
	bl_label = "Show/hide extra options"
	bl_idname = "ue4_tools.extra_options"
	bl_description = "Show/hide extra options"

	def execute(self, context):
		pp = bpy.context.scene.pivot_painter  
		pp.extraoptions = not pp.extraoptions
		return {'FINISHED'}


class PPB_OT_ShowHideExperimentalOptions(Operator):																# Extra options toggle
	bl_label = "Show/hide experimental options"
	bl_idname = "ue4_tools.experimental_options"
	bl_description = "Show/hide experimental options"

	def execute(self, context):
		pp = bpy.context.scene.pivot_painter  
		pp.experimentaloptions = not pp.experimentaloptions
		return {'FINISHED'}


class PPB_OT_CreateSelectOrder(Operator):																	# Create a custom property "SelectionOrder" based on the order the objects were selected
	bl_idname = "ue4_tools.create_select_order"
	bl_label = "Start selection order"
	bl_description = "Press button, then start selecting objects with preferred order.\nPress again to store order number in 'SelectionOrder' custom property.\n\nYou can select more than 1 object each time.\nPress ESC to cancel. "

	@classmethod
	def poll(self, context):
		return bpy.context.mode == 'OBJECT'

	orderarray = []											# Array with selected objects in order of selection
	prevlen = 0
	def update(self, context):								# Create the orderarray
		curlen = len(context.selected_objects)
		if curlen > self.prevlen:							# Selected more objects
			for obj in context.selected_objects:
				if obj not in self.orderarray:				# if obj are missing add to orderarray
					self.orderarray.append(obj)
		elif curlen < self.prevlen:							# Deselect objects
			for i, obj in enumerate(self.orderarray):
				if obj not in context.selected_objects:		# if obj are deselected  remove from  orderarray
					del self.orderarray[i]
		self.prevlen = len(self.orderarray)					# Store len to avoid calculation every update

	def execute(self, context):								# Used for panel draw. When button is pressed will hide operator from panel and in place will show selectingobjects bool
		pp = bpy.context.scene.pivot_painter 
		pp.selectingobjects = True

	def modal(self, context, event):
		pp = bpy.context.scene.pivot_painter 
		if pp.selectingobjects == False:					# Used to store order to objects when flip the boolean
			counter = pp.orderstart
			for obj in self.orderarray:
				obj["SelectionOrder"] = counter				# (order starts from 1 UE shader)
				if pp.dontcount==False:
					counter = counter +1
			return {'FINISHED'}			
		elif event.type == 'ESC':							# Cancel operation
			pp.selectingobjects = False
			context.area.tag_redraw()						# panel is lazy
			return {'CANCELLED'}
		self.update(context)
		return {'PASS_THROUGH'}

	def invoke(self, context, event):
		self.update(context)
		self.execute(context)
		context.window_manager.modal_handler_add(self)
		return {'RUNNING_MODAL'}


class PPB_OT_CreateTextures(Operator):																	# The button to create the textures
	bl_label = "Create Textures"
	bl_idname = "ue4_tools.create_textures"
	bl_description = "Save before use is advised.\n\nProgress report in system console. "

	@classmethod
	def poll(cls, context):
			return context.mode == 'OBJECT' # len(context.selected_objects) > 1  and  # and context.active_object.type == 'MESH'		# Check that you are ready to rumble.

	def execute(self, context):
		pp = context.scene.pivot_painter
		units = context.scene.unit_settings
		grandparentscount = 0
		objwithoutorder = []
		t1 = time.time()
		
		for obj in bpy.context.selected_objects:			
			if obj.parent == None :								# Check that there is at least one object with parent 
				grandparentscount= grandparentscount +1			# Only 1 object should have no parent (the base)
				break

		if pp.savetextures == True:														#Check that save is possible
			pathok = os.path.exists(bpy.path.abspath(pp.folderpath))
			if pathok == False:
				self.report({'ERROR'}, 'Incorrect Save location ' +str(pp.folderpath))
				return {'CANCELLED'}	

		warned = False
		hdrmismatch = 0
		testSelectionOrder = False
		testBoundBoxCenter = False
		rgb = (pp.rgb, pp.rgb2, pp.rgb3, pp.rgb4)
		alpha = (pp.alpha, pp.alpha2, pp.alpha3, pp.alpha4)
		for i in range(pp.totaltextures):
			if rgb[i] != 'None' or alpha[i] != 'None' :
				_, _, texturergb, texturealpha, hdr, hdra = texturefunction(pp, False, False, i)						# Find if rgb and alpha use Hdr and what the alpha channel is set to store
				if not ( rgb[i] == 'None' or alpha[i] == 'None' ) :														# In case the rbg or alpha is selected none hdr will stay false and the next test might fail
					if hdr != hdra : hdrmismatch = i +1 																# If HDR for rgb and alpha selection dont match save the texture number
				if texturealpha == "SelectionOrder": testSelectionOrder = True											# If alpha is set to selection order will need to check objects
				if (texturergb == "Xaxis" or texturealpha == "Xextent" or texturealpha == "Xwidth" ) and ( ( pp.firstlevel == True ) or ( pp.secondlevel == True ) or ( pp.thirdlevel == True ) or ( pp.fourthlevel == True ) ):
					testBoundBoxCenter = True																			# check if boundbox need testing

		if testSelectionOrder == True:
			for obj in bpy.context.selected_objects:															# Check that all objects have 'SelectionOrder' property. If not create a list for the user and cancel.
				try: obj["SelectionOrder"]
				except Exception:
					objwithoutorder.append(obj.name)
			if len(objwithoutorder) > 0:
				if len(objwithoutorder) < 4:	
					self.report({'ERROR'}, "Object " + str(objwithoutorder)+ " missing 'SelectionOrder' property")
				else:
					self.report({'INFO'}, " Objects missing 'SelectionOrder' property : " +  str(objwithoutorder))
					self.report({'ERROR'}, str(len(objwithoutorder)) + " Objects missing 'SelectionOrder' property\nList of the objects in the console. ")
				return {'CANCELLED'}

		if testBoundBoxCenter == True:
			for obj in bpy.context.selected_objects:
				vec1= mathutils.Vector ((obj.bound_box[0][0], obj.bound_box[0][1], obj.bound_box[0][2] ))				# Vector from the origin point to the min vertex position of the boundbox
				vec2= mathutils.Vector ((obj.bound_box[6][0], obj.bound_box[6][1], obj.bound_box[6][2] ))				# Max vertex is 6
				diagonalvector = vec1 -vec2																				# Vectors point to the opposite direction (if origin is in boundbox center)
				diagonallength = diagonalvector.length																	# The diagonal of bound box to get a base for comparison
				originvector = (vec1 + vec2) /2																			# Vector from origin to bound box center. if origin in the bound box center will give 0 vector
				originlength = originvector.length																		# size of vector from origin point to the 
				if originlength < diagonallength * 0.1:																	# The origin needs to be off-center. This is still too close, but should catch problems without bring headaches from couple bad objects.
#  %i of %i" % (idx, len(bpy.context.selected_objects)
					self.report({'WARNING'},"Found at least 1 object(%s) with origin point near the center of BoundBox. You can ignore this warning if the object/s is not set up to use Boundbox method. To calculate X axis from BoundBox, origin point needs to be off-center and rotation zero. To disable it, deselect all the boxes under 'Calculate X Axis from BoundBox' in the Extra Options" %(str(obj.name)))
					warned = True
					break
				if obj.rotation_euler[0]!=0 or obj.rotation_euler[1]!=0 or obj.rotation_euler[2]!=0 :
					self.report({'WARNING'}, "Found at least 1 object (" + str(obj.name) + ")  with non zero rotation ("+str(int(round(math.degrees(obj.rotation_euler[0])))) +", "+str(int(round(math.degrees(obj.rotation_euler[1]))))+", " +str(int(round(math.degrees(obj.rotation_euler[2])))) +"). To calculate X axis from BoundBox, origin point needs to be off-center and rotation zero. To disable it, uncheck all the boxes under 'Calculate X Axis from BoundBox' in the Extra Options")
					warned = True
					break
		
		if units.system != 'METRIC' or round(units.scale_length, 2) != 1:									# Numerous checks that everything is fine
			self.report({'ERROR'}, "Scene units must be Metric with a Unit Scale of 1!")
			return {'CANCELLED'}
		elif len(context.selected_objects) < 2:
			self.report({'ERROR'}, "Need more Objects!") 
			return {'CANCELLED'}
		elif len(context.selected_objects) == 1:
			self.report({'ERROR'}, "There is only 1 selected object")
			return {'CANCELLED'}
		elif grandparentscount == 0:
			self.report({'ERROR'}, "Objects have no base object!") 
			return {'CANCELLED'}
		elif pp.savetextures == True and pp.folderpath == '' :
			self.report({'ERROR'}, "No specified folder path") 
			return {'CANCELLED'}
		elif hdrmismatch > 0:
			self.report({'ERROR'}, "Texture " + str(hdrmismatch)+ " has mixed HDR and LDR texture selection") 
			return {'CANCELLED'}
		else:
			main(context)
			print('Blender GUI may take a moment to respond')
			if warned == False:
				self.report({'INFO'}, "Pivot Painter Done, total time: "+ str(time.time() - t1))
			else:
				self.report({'INFO'}, "Pivot Painter done with WARNING, total time: "+ str(time.time() - t1) + ". See info area or system console for more info")
			return {'FINISHED'}


class PPB_PT_panel:																			# THe panel in the UI
	bl_idname = "ue4_pivot_painter_panel"
	bl_label = "Pivot Painter"		
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'UI'
	#bl_context = "tool"
	#bl_category = "Unreal Tools"


	def draw(self, context):     												# draw a user interface		(# align = True # use_slider = True # use_pin=true)
		pp = bpy.context.scene.pivot_painter  
		col = self.layout.column()

		if pp.totaltextures >0 :
			col.label(text="1st Texture:")
			col.prop(pp, "rgb")
			col.prop(pp, "alpha")
		if pp.totaltextures >1 :
			col.label(text="2nd Texture:")
			col.prop(pp, "rgb2")
			col.prop(pp, "alpha2")
		if pp.totaltextures >2 :
			col.label(text="3rd Texture:")
			col.prop(pp, "rgb3")
			col.prop(pp, "alpha3")
		if pp.totaltextures ==4 :
			col.label(text="4th Texture:")
			col.prop(pp, "rgb4")
			col.prop(pp, "alpha4")		

		self.layout.row().separator()
		row = self.layout.row()														# Index options
		row.prop(pp, "automaticindexselect")
		sub=row.column()
		if pp.automaticindexselect == True:
			sub.enabled = False
		else:
			sub.enabled = True
		sub.prop(pp, "uvindex")
		col = self.layout.column()

		ext = col.row()																# Extra Options 
		if not pp.extraoptions:
			ext.operator("ue4_tools.extra_options", icon='TRIA_RIGHT', text="", emboss=False)
			extext = ext.row()
			extext.label(text="Extra Options")
		else:
			box = self.layout.box()
			ext = box.row()
			ext.operator("ue4_tools.extra_options", icon='TRIA_DOWN', text="", emboss=False)
			extext = ext.row()
			extext.label(text="Extra Options")

			row = box.row()
			row.prop(pp, "totaltextures")
									
			row1 = box.column()
			row1.scale_y = 1.5
			if not pp.selectingobjects:												# create select order (flip option to show operation running)
				row1.operator("ue4_tools.create_select_order")
			else:
				row1.prop(pp, "selectingobjects", toggle=True)
			row6 = box.row()
			row6.prop(pp, "orderstart")
			row6.prop(pp, "dontcount")

			col7 = box.column()			
			ext2 = col7.row()																# Experimental Options 			
			if not pp.experimentaloptions:
				ext2.operator("ue4_tools.experimental_options", icon='TRIA_RIGHT', text="", emboss=False)
				extext = ext2.row()
				extext.label(text="Axis from BoundBox (Experimental):")
			else:
				ext2.operator("ue4_tools.experimental_options", icon='TRIA_DOWN', text="", emboss=False)
				extext = ext2.row()
				extext.label(text="Calculate X Axis from BoundBox (Experimental):")
				col = box.column()							
				rows = col.row()
				rows.prop(pp, "firstlevel")
				rows.prop(pp, "secondlevel")
				rows.prop(pp, "thirdlevel")
				rows.prop(pp, "fourthlevel")
				row = self.layout.row()
				per = box.column()
				if ( pp.firstlevel == True ) or ( pp.secondlevel == True ) or ( pp.thirdlevel == True ) or ( pp.fourthlevel == True ):
						per.enabled = True
				else:
					per.enabled = False	
				per.prop(pp, "percentagefreedom", slider=True)



		col = self.layout.column()													# File options
		rows = col.row()
		rows.prop(pp, "createnew")
		rows.prop(pp, "savetextures")
		sub2 = self.layout.column()
		if pp.savetextures == True:
			sub2.enabled = True
		else:
			sub2.enabled = False		
		sub2.prop(pp, "folderpath")
		
		row = self.layout.row()
		row.scale_y = 2
		row.operator("ue4_tools.create_textures")

class VIEW3D_PT_pivot_painter_Object(Panel, PPB_PT_panel):
    bl_category = "Pivot Painter"
    bl_idname = "VIEW3D_PT_pivot_painter_object"
    bl_context = "objectmode"


classes = (
	VIEW3D_PT_pivot_painter_Object,																							
	#PPB_PT_panel,
	PPB_OT_CreateTextures,
	UE4_PivotPainterProperties,
	PPB_OT_ShowHideExtraOptions,
	PPB_OT_ShowHideExperimentalOptions,
	PPB_OT_CreateSelectOrder,
)

def register():
	from bpy.utils import register_class
	for cls in classes:
		register_class(cls)
	bpy.types.Scene.pivot_painter = PointerProperty(type = UE4_PivotPainterProperties)

def unregister():
	from bpy.utils import unregister_class
	for cls in reversed(classes):
		unregister_class(cls)
	del bpy.types.Scene.pivot_painter

if __name__ == "__main__":																					# For manual execution(testing)
 	register()
