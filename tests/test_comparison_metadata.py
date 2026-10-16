import asyncio
import json

from PySide6.QtGui import QImage

from comfyui_control.mobile.image_metadata import png_parameters, parameters
from comfyui_control.mobile.service import MobileService
from comfyui_control.mobile.settings import MobileSettings


def test_comparison_parameters_allowlist_excludes_prompt_and_secrets(tmp_path):
    graph={'model':{'class_type':'Loader','inputs':{'unet_name':'flux.gguf'}},
           'sample':{'class_type':'Sampler','inputs':{'steps':20,'cfg':3.5,'seed':18446744073709551600,'width':768,'height':1024,'api_key':'not-for-phone'}},
           'text':{'class_type':'Text','inputs':{'text':'private prompt'}}}
    image=QImage(8,16,QImage.Format.Format_RGB32)
    image.fill(0)
    image.setText('prompt',json.dumps(graph))
    path=tmp_path/'metadata.png'
    assert image.save(str(path))
    result=png_parameters(path,{})
    serialized=json.dumps(result)
    assert 'private prompt' not in serialized and 'not-for-phone' not in serialized
    assert {r['label'] for r in result} >= {'Diffusion model','Steps','CFG','Seed','Width','Height'}
    assert next(r['value'] for r in result if r['label']=='Seed')==18446744073709551600
    assert png_parameters(None,{})==[]
    assert parameters([{'role':'positive','key':'prompt'}],{'prompt':'private'})==[]


def test_comparison_respects_job_ownership_and_missing_images(tmp_path):
    async def scenario():
        service=MobileService(tmp_path,MobileSettings(),tmp_path/'out')
        item=service.image_ref({'filename':'one.png'},'one')
        service.jobs['one']={'owner':'first','controls':[{'role':'steps','key':'steps'}],'values':{'steps':30}}
        assert (await service.image_parameters(item['id'],'first'))[0]['value']==30
        assert await service.image_parameters(item['id'],'second')==[]
        import pytest
        with pytest.raises(ValueError):
            await service.image_parameters('../credentials','first')
    asyncio.run(scenario())
