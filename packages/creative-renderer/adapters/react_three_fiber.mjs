import React from 'react';
import {createRoot, advance, extend} from '@react-three/fiber';
import * as THREE from 'three';
import {canvas,sceneAt} from './common.mjs';
extend(THREE);
function outline(p,padding=0) {
  const shape=new THREE.Shape();
  if(p.kind==='ellipse') shape.absellipse(p.x,-p.y,p.width/2+padding,p.height/2+padding,0,Math.PI*2,false,0);
  else {const x=p.x-padding,y=p.y-padding,w=p.width+2*padding,h=p.height+2*padding;shape.moveTo(x,-y);shape.lineTo(x+w,-y);shape.lineTo(x+w,-y-h);shape.lineTo(x,-y-h);shape.closePath();}
  return shape;
}
function line(p) {
 const length=Math.hypot(p.width,p.height),nx=-p.height/length*p.stroke_width/2,ny=p.width/length*p.stroke_width/2;
 const shape=new THREE.Shape();shape.moveTo(p.x+nx,-p.y-ny);shape.lineTo(p.x+p.width+nx,-p.y-p.height-ny);shape.lineTo(p.x+p.width-nx,-p.y-p.height+ny);shape.lineTo(p.x-nx,-p.y+ny);shape.closePath();return shape;
}
export async function prepare(request) {
  const element = canvas(request); const root = createRoot(element);
  const {width,height} = request.dimensions;
  await root.configure({frameloop:'never',orthographic:true, camera:{position:[width/2,-height/2,100],zoom:1,near:0.1,far:1000},size:{width,height,top:0,left:0},gl:{preserveDrawingBuffer:true,antialias:true}});
  let previous=[];
  return async frame => {
    const geometries=[], meshes=[];
    function mesh(shape,color,key,z=0) {
      const geometry=new THREE.ShapeGeometry(shape);geometries.push(geometry);
      meshes.push(React.createElement('mesh',{key,geometry,position:[0,0,z]},React.createElement('meshBasicMaterial',{color,side:THREE.DoubleSide,toneMapped:false})));
    }
    sceneAt(request,frame).forEach((p,i)=>{
      if(p.kind==='line') {if(p.stroke_width>0)mesh(line(p),p.stroke,i);return;}
      mesh(outline(p),p.fill,`${i}-fill`);
      if(p.stroke_width>0){const stroke=outline(p,p.stroke_width/2);if(p.width>p.stroke_width && p.height>p.stroke_width)stroke.holes.push(outline(p,-p.stroke_width/2));mesh(stroke,p.stroke,`${i}-stroke`,0.1);}
    });
    root.render(React.createElement(React.Fragment,null,React.createElement('color',{attach:'background',args:[request.scene.background]}),...meshes));
    await new Promise(resolve=>setTimeout(resolve,30));
    advance(frame/(request.clock.fps_numerator/request.clock.fps_denominator),true);
    previous.forEach(geometry=>geometry.dispose());previous=geometries;
  };
}
