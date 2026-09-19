"""Lazy GPU lifetime and export-level bake telemetry."""
import time


class BakeSession:
    def __init__(self,mode='auto',log=print):
        if mode not in ('auto','cpu'):raise ValueError('Baking must be auto or cpu')
        self.mode=mode;self.log=log;self.gpu=None;self.disabled=False
        self.stats={'requested':mode,'device':None,'gpuPages':0,'cpuPages':0,
                    'fallbackReason':None,'seconds':0.,'chartSeconds':0.,'pixelSeconds':0.,'pngSeconds':0.}

    def prepare(self,images,recipe):
        if self.mode=='cpu' or self.disabled:return None
        try:
            if self.gpu is None:
                from .gpu_baking import GPUBaker
                self.gpu=GPUBaker();self.stats['device']=self.gpu.renderer
                self.log('GPU baking: '+self.gpu.renderer)
            self.gpu.prepare(images,recipe)
            return self.gpu
        except Exception as e:
            self.fallback(e);return None

    def fallback(self,error):
        self.disabled=True;self.stats['fallbackReason']=str(error)
        self.log('GPU baking unavailable; using CPU: '+str(error))
        self.close()

    def close(self):
        if self.gpu:
            try:self.gpu.close()
            finally:self.gpu=None
