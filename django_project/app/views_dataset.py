import os
import pickle
import logging
import json
import cv2
import shutil
import numpy as np
import pandas as pd

from pathlib import Path

from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings

from app.models import Project, Dataset
from app.forms import DatasetForm

from views_common import SidebarActiveStatus, get_version, load_dataset, get_jupyter_nb_url
from machine_learning.lib.utils.utils import save_image_files, save_table_info

# Create your views here.

def dataset(request):
    """ Function: dataset
     * dataset top
    """
    
    # --- reset dataset detail parameters ---
    if ('dropdown_dataset_info' in request.session.keys()):
        del request.session['dropdown_dataset_info']
        if ('selected_dataset_type' in request.session.keys()):
            del request.session['selected_dataset_type']
    
    if (request.method == 'POST'):
        if ('dataset_view_dropdown' in request.POST):
            logging.info('----------------------------------------')
            logging.info(f'[DEBUG] {request.method}')
            logging.info(f'[DEBUG] {request.POST}')
            logging.info(f'[DEBUG] {request.POST.getlist("dataset_view_dropdown")}')
            logging.info('----------------------------------------')
            request.session['dataset_view_dropdown_selected_project'] = request.POST.getlist('dataset_view_dropdown')[0]
        
        elif ('dataset_view_upload' in request.POST):
            form_custom_dataset = DatasetForm(request.POST, request.FILES)
            if (form_custom_dataset.is_valid()):
                # --- get related project ---
                project_name = request.session.get('dataset_view_dropdown_selected_project', None)
                project = Project.objects.get(name=project_name)
                
                # --- save model ---
                dataset = Dataset.objects.create(
                              name=form_custom_dataset.cleaned_data.get('name'),
                              project=project,
                              train_zip=form_custom_dataset.cleaned_data.get('train_zip'),
                              valid_zip=form_custom_dataset.cleaned_data.get('valid_zip'),
                              test_zip=form_custom_dataset.cleaned_data.get('test_zip'),
                              meta_zip=form_custom_dataset.cleaned_data.get('meta_zip'),
                              uploaded_at=form_custom_dataset.cleaned_data.get('uploaded_at'),
                              download_status=Dataset.STATUS_NONE,
                              image_gallery_status=Dataset.STATUS_NONE,
                          )
        
                # --- unzip ---
                logging.info('[INFO] unzip train.zip START')
                train_dir = Path(dataset.train_zip.path).parent
                shutil.unpack_archive(dataset.train_zip.path, train_dir)
                logging.info('[INFO] unzip train.zip DONE')
                
                if (dataset.test_zip.name):
                    logging.info('[INFO] unzip test.zip START')
                    test_dir  = Path(dataset.test_zip.path).parent
                    shutil.unpack_archive(dataset.test_zip.path, test_dir)
                    logging.info('[INFO] unzip test.zip DONE')
                
                if (dataset.valid_zip.name):
                    logging.info('[INFO] unzip validation.zip START')
                    valid_dir = Path(dataset.valid_zip.path).parent
                    shutil.unpack_archive(dataset.valid_zip.path, valid_dir)
                    logging.info('[INFO] unzip validation.zip DONE')
                
                logging.info('[INFO] unzip meta.zip START')
                meta_dir  = Path(dataset.meta_zip.path).parent
                shutil.unpack_archive(dataset.meta_zip.path, meta_dir)
                logging.info('[INFO] unzip meta.zip DONE')
                
                # --- preparing ---
                load_dataset(dataset)
                
        return redirect('dataset')
        
    else:
        project = Project.objects.all().order_by('-id').reverse()
        dataset = Dataset.objects.all().order_by('-id').reverse()
        sidebar_status = SidebarActiveStatus()
        sidebar_status.dataset = 'active'
        
        # check for existence of selected project name
        project_name_list = [p.name for p in project]
        selected_project_name = request.session.get('dataset_view_dropdown_selected_project', None)
        
        if ((selected_project_name is not None) and (selected_project_name in project_name_list)):
            dropdown_selected_project = Project.objects.get(name=selected_project_name)
        else:
            dropdown_selected_project = None
        
        form_custom_dataset = DatasetForm()
        
        logging.info('-------------------------------------')
        logging.info(project_name_list)
        logging.info(dropdown_selected_project)
        logging.info('-------------------------------------')
        context = {
            'project': project,
            'dataset': dataset,
            'sidebar_status': sidebar_status,
            'text': get_version(),
            'jupyter_nb_url': get_jupyter_nb_url(),
            'dropdown_selected_project': dropdown_selected_project,
            'form_custom_dataset': form_custom_dataset,
        }
        return render(request, 'dataset.html', context)

def dataset_detail(request, project_id, dataset_id):
    """ Function: dataset_detail
     * display dataset details(images, distribution, etc)
    """
    
    def _get_dataloader_obj(dataset):
        dataset_dir = Path(settings.MEDIA_ROOT, settings.DATASET_DIR, dataset.project.hash)
        download_dir = Path(dataset_dir, f'dataset_{dataset.id}')
        if (Path(download_dir, 'dataset.pkl').exists()):
            download_button_state = "disabled"
            with open(Path(download_dir, 'dataset.pkl'), 'rb') as f:
                dataloader_obj = pickle.load(f)
        else:
            download_button_state = ""
            dataloader_obj = None
        
        return dataloader_obj, download_button_state, download_dir
    
    
    # logging.info('-------------------------------------')
    # logging.info(request)
    # logging.info(request.method)
    # logging.info('-------------------------------------')
    
    project = get_object_or_404(Project, pk=project_id)
    dataset = get_object_or_404(Dataset, pk=dataset_id, project=project)
    
    dataset_info = []
    if (dataset.dataset_type == Dataset.DATASET_TYPE_IMAGE):
        dataset_info.append('Images')
    dataset_info.append('Statistics')
    
    if (request.method == 'POST'):
        logging.info('-------------------------------------')
        logging.info(request.POST)
        logging.info(request.POST.keys())
        logging.info('-------------------------------------')
        
        if ('dataset_download' in request.POST.keys()):
            # --- dataset download ---
            dataset.download_status = dataset.STATUS_PREPARING
            dataset.save()
            
            context = {
                'text': get_version(),
                'jupyter_nb_url': get_jupyter_nb_url(),
                'project_id': project.id,
                'dataset_id': dataset.id,
                'dataset_name': dataset.name,
                'download_status': dataset.download_status,
            }
            return render(request, 'dataset_detail.html', context)
        
        if ('dropdown_dataset_info' in request.POST.keys()):
            selected_dataset_info = request.POST['dropdown_dataset_info']
            request.session['dropdown_dataset_info'] = selected_dataset_info
            
            if ((selected_dataset_info == 'Images') and (dataset.image_gallery_status == dataset.STATUS_NONE)):
                dataset.image_gallery_status = dataset.STATUS_PREPARING
                dataset.save()
            
                dataloader_obj, download_button_state, download_dir = _get_dataloader_obj(dataset)
                context = {
                    'text': get_version(),
                    'jupyter_nb_url': get_jupyter_nb_url(),
                    'project_id': project.id,
                    'dataset_id': dataset.id,
                    'dataset_name': dataset.name,
                    'dataloader_obj': dataloader_obj,
                    'download_status': dataset.download_status,
                    'download_button_state': download_button_state,
                    'dataset_info': dataset_info,
                    'selected_dataset_info': selected_dataset_info,
                    'image_gallery_status': dataset.image_gallery_status,
                }
                return render(request, 'dataset_detail.html', context)
            
        if ('image_gallery_key' in request.POST.keys()):
            selected_dataset_type = request.POST['image_gallery_key']
            request.session['selected_dataset_type'] = selected_dataset_type
            request.session['image_gallery_page_now'] = 1
        
        if ('select_page' in request.POST.keys()):
            selected_page = int(request.POST['select_page'])
            request.session['image_gallery_page_now'] = selected_page
            
    # --- check dataset download ---
    if (dataset.download_status == dataset.STATUS_PREPARING):
        # --- load dataest and dataloader objects
        load_dataset(dataset)
        dataloader_obj, download_button_state, download_dir = _get_dataloader_obj(dataset)
        
        
        # --- load key_name from meta data ---
        df_meta = pd.read_json(Path(download_dir, 'meta', 'info.json'), typ='series')
        
        if (df_meta['input_type'] == 'image_data'):
            # --- get key_name ---
            for key in df_meta['keys']:
                if (key['type'] == 'image_file'):
                    key_name = key['name']
                    break
            
            # --- save image files ---
            if (dataloader_obj.train_x is not None):
                ids = np.arange(len(dataloader_obj.train_x))
                save_image_files(dataloader_obj.train_x, dataloader_obj.train_y, ids,
                                 Path(download_dir, 'train'), name='images', key_name=key_name)
            if (dataloader_obj.validation_x is not None):
                ids = np.arange(len(dataloader_obj.validation_x))
                save_image_files(dataloader_obj.validation_x, dataloader_obj.validation_y, ids,
                                 Path(download_dir, 'validation'), name='images', key_name=key_name)
            if (dataloader_obj.test_x is not None):
                ids = np.arange(len(dataloader_obj.test_x))
                save_image_files(dataloader_obj.test_x, dataloader_obj.test_y, ids,
                                 Path(download_dir, 'test'), name='images', key_name=key_name)
        
        elif (df_meta['input_type'] == 'table_data'):
            save_table_info(df_meta, dataloader_obj.train_x, dataloader_obj.train_y, Path(download_dir, 'train'))
            save_table_info(df_meta, dataloader_obj.validation_x, dataloader_obj.validation_y, Path(download_dir, 'validation'))
            save_table_info(df_meta, dataloader_obj.test_x, dataloader_obj.test_y, Path(download_dir, 'test'))
        
    # --- check download directory ---
    if (dataset.download_status == dataset.STATUS_DONE):
        dataloader_obj, download_button_state, download_dir = _get_dataloader_obj(dataset)
        
        # --- preparing to display images ---
        if (dataset.image_gallery_status == dataset.STATUS_PREPARING):
            logging.info('----------------------------------------')
            logging.info('Dataset preparing START')
            logging.info('----------------------------------------')
            
            dataset.image_gallery_status = dataset.STATUS_PROCESSING
            dataset.save()
            
            
            dataset.image_gallery_status = dataset.STATUS_DONE
            dataset.save()
            
            logging.info('----------------------------------------')
            logging.info('Dataset preparing DONE')
            logging.info('----------------------------------------')
            
        selected_dataset_info = request.session.get('dropdown_dataset_info', None)
        selected_dataset_type = request.session.get('selected_dataset_type', None)
        logging.info('-------------------------------------')
        logging.info(f'selected_dataset_info = {selected_dataset_info}')
        logging.info(f'selected_dataset_type = {selected_dataset_type}')
        logging.info('-------------------------------------')
        
        # --- set keys ---
        logging.info('-------------------------------------')
        logging.info(f'dataloader_obj.verified = {dataloader_obj.verified}')
        logging.info('-------------------------------------')
        image_gallery_keys = []
        if (dataloader_obj.verified):
            if (dataloader_obj.train_x is not None):
                image_gallery_keys.append('Train')
            if (dataloader_obj.validation_x is not None):
                image_gallery_keys.append('Validation')
            if (dataloader_obj.test_x is not None):
                image_gallery_keys.append('Test')
        
        # --- set image data file ---
        image_gallery_data = []
        if (selected_dataset_type is not None):
            images_page_now = request.session.get('image_gallery_page_now', 1)
            images_per_page = 50
            
            json_data = pd.read_json(Path(download_dir, selected_dataset_type.lower(), 'info.json'))
            
            images_page_max = len(json_data) // images_per_page
            images_page_list = [x for x in range(1, images_page_max+1)]
            
            # --- load key_name from meta data ---
            df_meta = pd.read_json(Path(download_dir, 'meta', 'info.json'), typ='series')
            for key in df_meta['keys']:
                if (key['type'] == 'image_file'):
                    key_name = key['name']
                    break
            json_data[key_name] = json_data[key_name].map(lambda x: Path(settings.MEDIA_URL,
                                                                     settings.DATASET_DIR,
                                                                     dataset.project.hash,
                                                                     f'dataset_{dataset.id}',
                                                                     selected_dataset_type.lower(),
                                                                     x))
            logging.info('----------------------------------------')
            logging.info(f'[DEBUG] {(images_page_now-1)*images_per_page}')
            logging.info(f'[DEBUG] {((images_page_now-1)*images_per_page)+images_per_page}')
            logging.info('----------------------------------------')
            image_gallery_data = json_data.iloc[(images_page_now-1)*images_per_page:((images_page_now-1)*images_per_page)+images_per_page].to_dict('r')
        else:
            images_page_now = 1
            images_page_max = 1
            images_page_list = []
            
        
        context = {
            'text': get_version(),
            'jupyter_nb_url': get_jupyter_nb_url(),
            'dataset_name': dataset.name,
            'dataloader_obj': dataloader_obj,
            'download_status': dataset.download_status,
            'download_button_state': download_button_state,
            'dataset_info': dataset_info,
            'selected_dataset_info': selected_dataset_info,
            'image_gallery_status': dataset.image_gallery_status,
            'image_gallery_keys': image_gallery_keys,
            'image_gallery_selected_item': selected_dataset_type,
            'image_gallery_data': image_gallery_data,
            'images_page_now': images_page_now,
            'images_page_max': images_page_max,
            'images_page_list': images_page_list,
        }
        return render(request, 'dataset_detail.html', context)
    else:
        context = {
            'text': get_version(),
            'jupyter_nb_url': get_jupyter_nb_url(),
            'dataset_name': dataset.name,
            'download_status': dataset.download_status,
        }
        return render(request, 'dataset_detail.html', context)

