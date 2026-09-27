import numpy as np

SLOTS = ('_BaseTexture', '_Albedo1', '_Albedo2', '_BaseNormal', '_Normal1')
DEFAULTS = ((0,0,0,1), (1,1,1,1), (1,1,1,1), (.5,.5,1,1), (.5,.5,1,1))
PARAMS = {'_MaskLayer2':0, '_SmoothnessScale2':0, '_Smoothness2':.1,
          '_waterSmoothMult':1, '_BumpScale':1, '_BaseMetallic':0,
          '_Metallic1':.3, '_Metallic2':.3, '_waterHeight':-100,
          '_waterTrans':0, '_albedoMult':.2, '_smoothMult':3, '_metallicMult':1}

SHADER = r'''#version 430 core
layout(local_size_x=8, local_size_y=8) in;
layout(std430,binding=0) readonly buffer Charts { vec4 c[]; };
layout(std430,binding=1) readonly buffer Tiles { ivec4 tiles[]; };
layout(rgba8,binding=0) writeonly uniform image2D outColor;
layout(rgba8,binding=1) writeonly uniform image2D outNormal;
layout(rgba8,binding=2) writeonly uniform image2D outMR;
uniform sampler2D tex0,tex1,tex2,tex3,tex4;
uniform vec4 transforms[5];
uniform float params[13];
uniform ivec3 flags;
uniform int tileOffset;

// Match the reference's repeat, top-left image convention and bilinear
// interpolation in linear space. texelFetch avoids hardware filter precision.
vec4 fetchRepeat(sampler2D t, ivec2 p, ivec2 size) {
    return texelFetch(t, (p + size) % size, 0);
}
vec4 sampleLayer(sampler2D t, vec2 uv, vec4 st) {
    vec2 q=uv*st.xy+st.zw; q.y=1-q.y;
    ivec2 size=textureSize(t,0);
    vec2 p=fract(q)*vec2(size)-.5;
    ivec2 ij=ivec2(floor(p)); vec2 f=fract(p);
    return mix(mix(fetchRepeat(t,ij,size),fetchRepeat(t,ij+ivec2(1,0),size),f.x),
               mix(fetchRepeat(t,ij+ivec2(0,1),size),fetchRepeat(t,ij+ivec2(1,1),size),f.x),f.y);
}
vec3 toSrgb(vec3 x) {
    x=max(x,vec3(0));
    return mix(1.055*pow(x,vec3(1./2.4))-.055,x*12.92,lessThanEqual(x,vec3(.0031308)));
}
vec4 quantize(vec3 x) {return vec4(roundEven(clamp(x,0,1)*255)/255,1);}
void main() {
    ivec4 tile=tiles[tileOffset+int(gl_WorkGroupID.x)];
    int b=tile.x*12;
    ivec2 pixel=tile.yz+ivec2(gl_LocalInvocationID.xy);
    if(any(greaterThanEqual(pixel,ivec2(c[b].zw)))) return;
    vec2 bc12=c[b+1].xy+c[b+1].zw*float(pixel.x)+c[b+2].xy*float(pixel.y);
    vec3 bc=max(vec3(1-bc12.x-bc12.y,bc12),vec3(0)); bc/=bc.x+bc.y+bc.z;
    vec2 uv=c[b+3].xy*bc.x+c[b+3].zw*bc.y+c[b+4].xy*bc.z;
    vec4 color=c[b+5]*bc.x+c[b+6]*bc.y+c[b+7]*bc.z;
    float height=dot(c[b+8].xyz,bc);
    float r=flags.x!=0 ? clamp(color.r,0,1):0;
    float g=flags.y!=0 ? min(clamp(color.g,0,1),1-r*(1-params[0])):0;
    vec3 base=sampleLayer(tex0,uv,transforms[0]).rgb;
    vec3 first=sampleLayer(tex1,uv,transforms[1]).rgb;
    vec3 second=sampleLayer(tex2,uv,transforms[2]).rgb;
    vec3 albedo=mix(mix(base,first,r),second,g);
    vec3 packedNormal=mix(sampleLayer(tex3,uv,transforms[3]).rgb,sampleLayer(tex4,uv,transforms[4]).rgb,r);
    float smoothness=packedNormal.b+g*params[1]*(params[2]-packedNormal.b);
    vec2 xy=mix(packedNormal.xy,vec2(.5),clamp(g*params[3],0,1));
    xy=(xy*2-1)*params[4];
    vec3 normal=vec3(xy,sqrt(max(0,1-dot(xy,xy))));
    normal/=max(length(normal),1e-12);
    if(c[b+2].z!=0) normal=vec3(0,0,1);
    float metallic=mix(mix(params[5],params[6],r),params[7],g);
    float h=clamp((height-params[8])/max(params[9],.01),0,1);
    float wet=(1-h*h*(3-2*h))*color.b;
    if(flags.z!=0) wet+=clamp(color.g,0,1)*(1-wet);
    albedo*=1+wet*(params[10]-1);
    smoothness*=1+wet*(params[11]-1);
    metallic*=1+wet*(params[12]-1);
    ivec2 dst=ivec2(c[b].xy)+pixel;
    imageStore(outColor,dst,quantize(toSrgb(albedo)));
    imageStore(outNormal,dst,quantize(normal*.5+.5));
    imageStore(outMR,dst,quantize(vec3(1,1-clamp(smoothness,0,1),clamp(metallic,0,1))));
}
'''


class GPUUnavailable(RuntimeError):
    pass


class GPUBaker:
    def __init__(self):
        self.window=None;self.program=None;self.textures=[];self.glfw=None
        try:
            import glfw
            from OpenGL import GL as gl
            from OpenGL.GL.shaders import compileShader, compileProgram
            self.glfw=glfw;self.gl=gl
            if not glfw.init():raise GPUUnavailable('GLFW initialization failed')
            glfw.window_hint(glfw.VISIBLE,glfw.FALSE)
            glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR,4)
            glfw.window_hint(glfw.CONTEXT_VERSION_MINOR,3)
            glfw.window_hint(glfw.OPENGL_PROFILE,glfw.OPENGL_CORE_PROFILE)
            self.window=glfw.create_window(1,1,'CODM bake worker',None,None)
            if not self.window:raise GPUUnavailable('OpenGL 4.3 is unavailable')
            glfw.make_context_current(self.window)
            self.renderer=gl.glGetString(gl.GL_RENDERER).decode('utf-8','replace')
            if any(s in self.renderer.lower() for s in ('llvmpipe','softpipe','software','gdi generic')):
                raise GPUUnavailable('Software OpenGL renderer: '+self.renderer)
            self.program=compileProgram(compileShader(SHADER,gl.GL_COMPUTE_SHADER))
            self.max_texture=int(gl.glGetIntegerv(gl.GL_MAX_TEXTURE_SIZE))
            self.max_groups=int(np.asarray(gl.glGetIntegeri_v(gl.GL_MAX_COMPUTE_WORK_GROUP_COUNT,0)).flat[0])
        except Exception as e:
            self.close()
            raise GPUUnavailable(str(e)) from e

    def prepare(self,images,recipe):
        gl=self.gl;self.release_surface();gl.glUseProgram(self.program)
        try:
            for i,(slot,default) in enumerate(zip(SLOTS,DEFAULTS)):
                pixels=np.ascontiguousarray(images.get(slot,np.array([[default]],dtype=np.float32)),dtype=np.float32)
                h,w=pixels.shape[:2]
                if max(w,h)>self.max_texture:raise GPUUnavailable('Source texture exceeds GPU size limit')
                tex=int(gl.glGenTextures(1));self.textures.append(tex)
                gl.glActiveTexture(gl.GL_TEXTURE0+i);gl.glBindTexture(gl.GL_TEXTURE_2D,tex)
                gl.glTexParameteri(gl.GL_TEXTURE_2D,gl.GL_TEXTURE_MIN_FILTER,gl.GL_NEAREST)
                gl.glTexParameteri(gl.GL_TEXTURE_2D,gl.GL_TEXTURE_MAG_FILTER,gl.GL_NEAREST)
                gl.glTexImage2D(gl.GL_TEXTURE_2D,0,gl.GL_RGBA32F,w,h,0,gl.GL_RGBA,gl.GL_FLOAT,pixels)
                gl.glUniform1i(gl.glGetUniformLocation(self.program,'tex'+str(i)),i)
            transforms=np.array([recipe['textures'].get(s,{}).get('transform',[1,1,0,0]) for s in SLOTS],dtype=np.float32)
            gl.glUniform4fv(gl.glGetUniformLocation(self.program,'transforms'),5,transforms)
            floats=np.array([recipe['floats'].get(k,v) for k,v in PARAMS.items()],dtype=np.float32)
            gl.glUniform1fv(gl.glGetUniformLocation(self.program,'params'),len(floats),floats)
            flags=[int(k in recipe['keywords']) for k in ('_ALBEDO_VERTEX_R','_ALBEDO_VERTEX_G','_use_g_control_wet_ON')]
            gl.glUniform3i(gl.glGetUniformLocation(self.program,'flags'),*flags)
        except Exception:
            self.release_surface();raise

    def page(self,mesh,entries,width,height,pad):
        if max(width,height)>self.max_texture:raise GPUUnavailable('Atlas exceeds GPU size limit')
        gl=self.gl;records=np.zeros((len(entries),12,4),dtype=np.float32);tiles=[]
        for i,((face,lo,hi,size,scale,u,degenerate),x,y) in enumerate(entries):
            w,h=map(int,size);cw,ch=w+2*pad+1,h+2*pad+1
            inv=np.linalg.inv(np.stack((u[1]-u[0],u[2]-u[0])))
            step=(hi-lo)/size
            records[i,0]=[x,y,cw,ch]
            records[i,1,:2]=(lo-step*pad-u[0])@inv
            records[i,1,2:]=[step[0],0]@inv
            records[i,2,:2]=[0,step[1]]@inv;records[i,2,2]=degenerate
            records[i,3]=mesh['uv'][face[:2]].reshape(-1)
            records[i,4,:2]=mesh['uv'][face[2]]
            records[i,5:8]=mesh['colors'][face]
            records[i,8,:3]=mesh['vertices'][face,1]
            tx,ty=np.meshgrid(np.arange(0,cw,8),np.arange(0,ch,8))
            tasks=np.zeros((tx.size,4),dtype=np.int32)
            tasks[:,0]=i;tasks[:,1]=tx.ravel();tasks[:,2]=ty.ravel();tiles.append(tasks)
        tasks=np.concatenate(tiles);buffers=[];outputs=[]
        try:
            for binding,data in enumerate((records,tasks)):
                buf=int(gl.glGenBuffers(1));buffers.append(buf)
                gl.glBindBuffer(gl.GL_SHADER_STORAGE_BUFFER,buf)
                gl.glBufferData(gl.GL_SHADER_STORAGE_BUFFER,data.nbytes,data,gl.GL_STATIC_DRAW)
                gl.glBindBufferBase(gl.GL_SHADER_STORAGE_BUFFER,binding,buf)
            for i in range(3):
                tex=int(gl.glGenTextures(1));outputs.append(tex)

                gl.glActiveTexture(gl.GL_TEXTURE0+5);gl.glBindTexture(gl.GL_TEXTURE_2D,tex)
                gl.glTexStorage2D(gl.GL_TEXTURE_2D,1,gl.GL_RGBA8,width,height)

                zeros=np.zeros((height,width,4),dtype=np.uint8)
                gl.glTexSubImage2D(gl.GL_TEXTURE_2D,0,0,0,width,height,gl.GL_RGBA,gl.GL_UNSIGNED_BYTE,zeros)
                gl.glBindImageTexture(i,tex,0,False,0,gl.GL_WRITE_ONLY,gl.GL_RGBA8)
            for offset in range(0,len(tasks),min(self.max_groups,8192)):
                gl.glUniform1i(gl.glGetUniformLocation(self.program,'tileOffset'),offset)
                gl.glDispatchCompute(min(len(tasks)-offset,self.max_groups,8192),1,1)

                gl.glFinish()
            gl.glMemoryBarrier(gl.GL_TEXTURE_UPDATE_BARRIER_BIT|gl.GL_SHADER_IMAGE_ACCESS_BARRIER_BIT)
            result=[]
            for tex in outputs:
                gl.glBindTexture(gl.GL_TEXTURE_2D,tex)
                pixels=np.empty((height,width,4),dtype=np.uint8)
                gl.glGetTexImage(gl.GL_TEXTURE_2D,0,gl.GL_RGBA,gl.GL_UNSIGNED_BYTE,pixels)
                result.append(pixels[:,:,:3].copy())
            return result
        finally:
            if outputs:gl.glDeleteTextures(outputs)
            if buffers:gl.glDeleteBuffers(len(buffers),buffers)

    def release_surface(self):
        if self.textures:self.gl.glDeleteTextures(self.textures);self.textures=[]

    def close(self):
        if self.window:
            try:
                self.glfw.make_context_current(self.window)
                self.release_surface()
                if self.program:self.gl.glDeleteProgram(self.program)
            except Exception:


                pass
            finally:self.glfw.destroy_window(self.window);self.window=None
        if self.glfw:self.glfw.terminate()

