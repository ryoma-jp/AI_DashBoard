import os
import json
import subprocess
import logging

from pathlib import Path

from django.shortcuts import render, redirect

from app.models import Project, MlModel, Dataset

from views_common import SidebarActiveStatus, get_version, get_jupyter_nb_url, get_dataloader_obj

# Create your views here.

def inference(request):
    """ Function: inference
     * inference top
    """
    def _get_selected_object():
        project_name = request.session.get('inference_view_selected_project', None)
        selected_project = Project.objects.get(name=project_name)
        
        model_name = request.session.get('inference_view_selected_model', None)
        selected_model = MlModel.objects.get(name=model_name, project=selected_project)
        
        return selected_project, selected_model
    
    def _inference_run():
        selected_project, selected_model = _get_selected_object()
        if (selected_model):
            logging.debug(selected_model)
            
            # --- Load config ---
            config_path = Path(selected_model.model_dir, 'config.json')
            with open(config_path, 'r') as f:
                config_data = json.load(f)
            
            # --- Predict ---
            main_path = Path('./app/machine_learning/main.py').resolve()
            logging.debug(f'main_path: {main_path}')
            logging.debug(f'current working directory: {os.getcwd()}')
            subproc_inference = subprocess.Popen(['python', main_path, '--mode', 'predict', '--config', config_path])
    
    # logging.info('-------------------------------------')
    # logging.info(request.method)
    # logging.info(request.POST)
    # logging.info('-------------------------------------')
    if (request.method == 'POST'):
        if ('inference_view_project_dropdown' in request.POST):
            request.session['inference_view_selected_project'] = request.POST.getlist('inference_view_project_dropdown')[0]
                
        elif ('inference_view_model_dropdown' in request.POST):
            curr_project = Project.objects.get(name=request.session['inference_view_selected_project'])
            
            if 'inference_view_selected_model' in request.session.keys():
                prev_model = MlModel.objects.get(name=request.session['inference_view_selected_model'], project=curr_project)
            else:
                prev_model = None
            
            request.session['inference_view_selected_model'] = request.POST.getlist('inference_view_model_dropdown')[0]
            curr_model = MlModel.objects.get(name=request.session['inference_view_selected_model'], project=curr_project)
            
        elif ('inference_view_dataset_dropdown' in request.POST):
            pass
            # (T.B.D)
            #   * dataset dropdown will be selected dataset that user required to inference
            
            # for debug
            # request.session['inference_view_selected_dataset'] = request.POST.getlist('inference_view_dataset_dropdown')[0]
            # curr_project = Project.objects.get(name=request.session['inference_view_selected_project'])
            # curr_dataset = Dataset.objects.get(name=request.session['inference_view_selected_dataset'], project=curr_project)
            
        elif ('inference_run' in request.POST):
            _inference_run()
        
        elif ('prediction_filter' in request.POST):
            request.session['prediction_filter'] = request.POST.getlist('prediction_filter')[0]
        
        else:
            logging.warning('Unknown POST command:')
            logging.warning(request.POST)
        
        return redirect('inference')
    else:
        sidebar_status = SidebarActiveStatus()
        sidebar_status.inference = 'active'
        
        project = Project.objects.all().order_by('-id').reverse()
        
        # check for existence of selected project name
        project_name_list = [p.name for p in project]
        selected_project_name = request.session.get('inference_view_selected_project', None)
        
        logging.info('-------------------------------------')
        logging.info(project_name_list)
        logging.info(selected_project_name)
        logging.info('-------------------------------------')
        
        if ((selected_project_name is not None) and (selected_project_name in project_name_list)):
            project_dropdown_selected = Project.objects.get(name=selected_project_name)
        else:
            project_dropdown_selected = None
        
        if (project_dropdown_selected):
            # --- get model list and selected model ---
            model = MlModel.objects.filter(project=project_dropdown_selected).order_by('-id').reverse()
            
            model_name = request.session.get('inference_view_selected_model', None)
            if (model_name is not None):
                model_dropdown_selected = MlModel.objects.get(name=model_name, project=project_dropdown_selected)
            else:
                model_dropdown_selected = None
            
            # --- get dataset list and selected dataset (T.B.D) ---
            dataset = Dataset.objects.filter(project=project_dropdown_selected).order_by('-id').reverse()
            if (model_dropdown_selected is not None):
                dataset_dropdown_selected = model_dropdown_selected.dataset
            else:
                dataset_dropdown_selected = None
            
            #
            #dataset_name_list = [d.name for d in Dataset.objects.all().order_by('-id')]
            #selected_dataset_name = request.session.get('inference_view_selected_dataset', None)
            #logging.info('-------------------------------------')
            #logging.info(dataset_name_list)
            #logging.info(selected_dataset_name)
            #logging.info('-------------------------------------')
            #if ((selected_dataset_name is not None) and (selected_dataset_name in dataset_name_list)):
            #    dataset_dropdown_selected = Dataset.objects.get(name=selected_dataset_name, project=project_dropdown_selected)
            #else:
            #    dataset_dropdown_selected = None
            
            
        else:
            model = MlModel.objects.all().order_by('-id').reverse()
            model_dropdown_selected = None
        
            dataset = Dataset.objects.all().order_by('-id').reverse()
            dataset_dropdown_selected = None
        
        # --- Check prediction filter ---
        prediction_filter_selected = request.session.get('prediction_filter', 'All')
        
        # --- Load DataLoader object and prediction ---
        if (dataset_dropdown_selected is not None):
            # --- get DataLoader object ---
            dataloader_obj = get_dataloader_obj(dataset_dropdown_selected)
            
            # --- get prediction ---
            prediction_json = Path(model_dropdown_selected.model_dir, 'prediction.json')
            if (prediction_json.exists()):
                with open(prediction_json, 'r') as f:
                    prediction = json.load(f)
            else:
                prediction = None
        else:
            dataloader_obj = None
            prediction = None
        
        
        context = {
            'project': project,
            'model': model,
            'dataset': dataset,
            'sidebar_status': sidebar_status,
            'text': get_version(),
            'jupyter_nb_url': get_jupyter_nb_url(),
            'project_dropdown_selected': project_dropdown_selected,
            'model_dropdown_selected': model_dropdown_selected,
            'dataset_dropdown_selected': dataset_dropdown_selected,
            'prediction': prediction,
            'prediction_filter_selected': prediction_filter_selected,
            'dataloader_obj': dataloader_obj,
        }
        return render(request, 'inference.html', context)

