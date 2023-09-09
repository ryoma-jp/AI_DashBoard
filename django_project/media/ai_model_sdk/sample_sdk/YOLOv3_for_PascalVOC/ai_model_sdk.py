
import os
import numpy as np
import pandas as pd
import cv2
import fcntl
import pickle
from pathlib import Path
from PIL import Image
from machine_learning.lib.utils.utils import save_config
from sklearn.metrics import accuracy_score

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.utils import to_categorical

from machine_learning.lib.trainer.tf_models.yolov3 import models as yolov3_models
from machine_learning.lib.trainer.tf_models.yolov3.utils import freeze_all as yolov3_freeze_all
from machine_learning.lib.trainer.tf_models.yolov3.utils import load_darknet_weights as yolov3_load_darknet_weights
from machine_learning.lib.utils.utils import download_file
from machine_learning.lib.data_loader.data_loader import load_dataset_from_tfrecord

#---------------------------------
# Set environ
#---------------------------------
os.environ["TF_FORCE_GPU_ALLOW_GROWTH"]= "true"

class AI_Model_SDK():
    """AI Model SDK
    
    Sample SDK for training YOLOv3 using PascalVOC dataset
    """
    __version__ = 'YOLOv3 for PascalVOC v0.0.1'

    class CustomCallback(keras.callbacks.Callback):
        def __init__(self, trainer_ctrl_fifo):
            super().__init__()
            self.trainer_ctrl_fifo = trainer_ctrl_fifo
            
        def on_train_batch_end(self, batch, logs=None):
            if (self.trainer_ctrl_fifo is not None):
                fd = os.open(self.trainer_ctrl_fifo, os.O_RDONLY | os.O_NONBLOCK)
                flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                flags &= ~os.O_NONBLOCK
                fcntl.fcntl(fd, fcntl.F_SETFL, flags)
                
                try:
                    command = os.read(fd, 128)
                    command = command.decode()[:-1]
                    while (True):
                        buf = os.read(fd, 65536)
                        if not buf:
                            break
                finally:
                    os.close(fd)
            
                if (command):
                    if (command == 'stop'):
                        print('End batch: recv command={}'.format(command))
                        self.model.stop_training = True
                    else:
                        print('End batch: recv unknown command={}'.format(command))
            
        def on_epoch_end(self, epoch, logs=None):
            keys = list(logs.keys())
            log_str = ''
            for key in keys[:-1]:
                log_str += '({} = {}), '.format(key, logs[key])
            log_str += '({} = {})'.format(keys[-1], logs[keys[-1]])
            print("End epoch {}: {}".format(epoch, log_str))

    def __init__(self, dataset_path, model_params, web_app_ctrl_fifo=None, trainer_ctrl_fifo=None):
        """Constructor

        Args:
            dataset_path (string) : file path of dataset.pkl (is DataLoader object)
                                      - attributes
                                        - train_dataset (dict)
                                        - validation_dataset (dict)
                                        - test_dataset (dict)
                                      - dict keys
                                        - 'tfrecord_path': path to tfrecord file
                                        - 'class_name_file_path': path to class name file
                                        - 'model_input_size': model input size
            model_params (dict) : AI model parameters
                                    - 'model_path': path to save trained model
        """

        #def split_input_and_target(dataset_params):
        #    """Split Data to Input and Target
        #    Split input samples and target from each ``info.json`` files
        #    """
        #    x_train = y_train = x_val = y_val = x_test = y_test = x_inference = y_inference = None
#
        #    if (('meta' in dataset_params.keys()) and (dataset_params['meta'] is not None)):
        #        df_meta = pd.read_json(dataset_params['meta'])
        #        input_key_list = [key['name'] for key in df_meta['keys']]
#
        #        print(dataset_params)
        #        if (('train' in dataset_params.keys()) and (dataset_params['train'] is not None)):
        #            df_train = pd.read_json(dataset_params['train'])
        #            x_train = df_train[['id'] + input_key_list]
        #            y_train = df_train[['id', 'target']]
#
        #        if (('val' in dataset_params.keys()) and (dataset_params['val'] is not None)):
        #            df_val = pd.read_json(dataset_params['val'])
        #            x_val = df_val[['id'] + input_key_list]
        #            y_val = df_val[['id', 'target']]
#
        #        if (('test' in dataset_params.keys()) and (dataset_params['test'] is not None)):
        #            df_test = pd.read_json(dataset_params['test'])
        #            x_test = df_test[['id'] + input_key_list]
        #            y_test = df_test[['id', 'target']]
#
        #        if (('inference' in dataset_params.keys()) and (dataset_params['inference'] is not None)):
        #            df_inference = pd.read_json(dataset_params['inference'])
        #            x_inference = df_inference[['id'] + input_key_list]
        #            y_inference = df_inference[['id', 'target']]
#
        #    return x_train, y_train, x_val, y_val, x_test, y_test, x_inference, y_inference
        
        @tf.function
        def transform_targets_for_output(y_true, grid_size, anchor_idxs):
            # y_true: (N, boxes, (x1, y1, x2, y2, class, best_anchor))
            N = tf.shape(y_true)[0]

            # y_true_out: (N, grid, grid, anchors, [x1, y1, x2, y2, obj, class])
            y_true_out = tf.zeros(
                (N, grid_size, grid_size, tf.shape(anchor_idxs)[0], 6))

            anchor_idxs = tf.cast(anchor_idxs, tf.int32)

            indexes = tf.TensorArray(tf.int32, 1, dynamic_size=True)
            updates = tf.TensorArray(tf.float32, 1, dynamic_size=True)
            idx = 0
            for i in tf.range(N):
                for j in tf.range(tf.shape(y_true)[1]):
                    if tf.equal(y_true[i][j][2], 0):
                        continue
                    anchor_eq = tf.equal(
                        anchor_idxs, tf.cast(y_true[i][j][5], tf.int32))

                    if tf.reduce_any(anchor_eq):
                        box = y_true[i][j][0:4]
                        box_xy = (y_true[i][j][0:2] + y_true[i][j][2:4]) / 2

                        anchor_idx = tf.cast(tf.where(anchor_eq), tf.int32)
                        grid_xy = tf.cast(box_xy // (1/grid_size), tf.int32)

                        # grid[y][x][anchor] = (tx, ty, bw, bh, obj, class)
                        indexes = indexes.write(
                            idx, [i, grid_xy[1], grid_xy[0], anchor_idx[0][0]])
                        updates = updates.write(
                            idx, [box[0], box[1], box[2], box[3], 1, y_true[i][j][4]])
                        idx += 1

            # tf.print(indexes.stack())
            # tf.print(updates.stack())

            return tf.tensor_scatter_nd_update(
                y_true_out, indexes.stack(), updates.stack())
        
        def transform_targets(y_train, anchors, anchor_masks, size):
            y_outs = []
            grid_size = size // 32

            # calculate anchor index for true boxes
            anchors = tf.cast(anchors, tf.float32)
            anchor_area = anchors[..., 0] * anchors[..., 1]
            box_wh = y_train[..., 2:4] - y_train[..., 0:2]
            box_wh = tf.tile(tf.expand_dims(box_wh, -2),
                             (1, 1, tf.shape(anchors)[0], 1))
            box_area = box_wh[..., 0] * box_wh[..., 1]
            intersection = tf.minimum(box_wh[..., 0], anchors[..., 0]) * \
                tf.minimum(box_wh[..., 1], anchors[..., 1])
            iou = intersection / (box_area + anchor_area - intersection)
            anchor_idx = tf.cast(tf.argmax(iou, axis=-1), tf.float32)
            anchor_idx = tf.expand_dims(anchor_idx, axis=-1)

            y_train = tf.concat([y_train, anchor_idx], axis=-1)

            for anchor_idxs in anchor_masks:
                y_outs.append(transform_targets_for_output(
                    y_train, grid_size, anchor_idxs))
                grid_size *= 2

            return tuple(y_outs)
        
        def transform_images(x_train, size):
            x_train = tf.image.resize(x_train, (size, size))
            x_train = x_train / 255
            return x_train
        
        # --- initialize parameters ---
        self.input_shape = [416, 416, 3]    # [H, W, C]
        self.class_num = 20
        self.model_path = model_params['model_path']
        self.trainer_ctrl_fifo = None
        self.web_app_ctrl_fifo = web_app_ctrl_fifo
        self.trainer_ctrl_fifo = trainer_ctrl_fifo
        self.task = 'object_detection'
        self.decoded_preds = {}
        self.get_feature_map = False

        self.batch_size = 32
        self.epochs = 100
        self.learning_rate = 0.001
        self.weight_decay = 0.004

        self.anchors = yolov3_models.yolo_anchors
        self.anchor_masks = yolov3_models.yolo_anchor_masks

        # --- load dataset ---
        with open(dataset_path, 'rb') as f:
            dataset = pickle.load(f)

        self.train_dataset = load_dataset_from_tfrecord(
            dataset.train_dataset['tfrecord_path'], 
            dataset.train_dataset['class_name_file_path'],
            dataset.train_dataset['model_input_size'])
        self.train_dataset = self.train_dataset.shuffle(buffer_size=512)
        self.train_dataset = self.train_dataset.batch(self.batch_size)
        self.train_dataset = self.train_dataset.map(lambda x, y: (
            transform_images(x, dataset.train_dataset['model_input_size']),
            transform_targets(y, self.anchors, self.anchor_masks, dataset.train_dataset['model_input_size'])))
        self.train_dataset = self.train_dataset.prefetch(
            buffer_size=tf.data.experimental.AUTOTUNE)

        self.validation_dataset = load_dataset_from_tfrecord(
            dataset.validation_dataset['tfrecord_path'], 
            dataset.validation_dataset['class_name_file_path'],
            dataset.validation_dataset['model_input_size'])
        self.validation_dataset = self.validation_dataset.shuffle(buffer_size=512)
        self.validation_dataset = self.validation_dataset.batch(self.batch_size)
        self.validation_dataset = self.validation_dataset.map(lambda x, y: (
            transform_images(x, dataset.validation_dataset['model_input_size']),
            transform_targets(y, self.anchors, self.anchor_masks, dataset.validation_dataset['model_input_size'])))
        self.validation_dataset = self.validation_dataset.prefetch(
            buffer_size=tf.data.experimental.AUTOTUNE)
        
        self.test_dataset = load_dataset_from_tfrecord(
            dataset.test_dataset['tfrecord_path'], 
            dataset.test_dataset['class_name_file_path'],
            dataset.test_dataset['model_input_size'])
        self.test_dataset = self.test_dataset.shuffle(buffer_size=512)
        self.test_dataset = self.test_dataset.batch(self.batch_size)
        self.test_dataset = self.test_dataset.map(lambda x, y: (
            transform_images(x, dataset.test_dataset['model_input_size']),
            transform_targets(y, self.anchors, self.anchor_masks, dataset.test_dataset['model_input_size'])))
        self.test_dataset = self.test_dataset.prefetch(
            buffer_size=tf.data.experimental.AUTOTUNE)
        
        ## --- load info.json ---
        #self.x_train_info, self.y_train_info, \
        #self.x_val_info, self.y_val_info, \
        #self.x_test_info, self.y_test_info, \
        #self.x_inference_info, self.y_inference_info \
        #    = split_input_and_target(dataset_params)
#
        ## --- replace path to absolute path ---
        #if (self.x_train_info is not None):
        #    self.x_train_info['img_file'] = self.x_train_info['img_file'].map(lambda x: Path(Path(dataset_params['train']).parent, x))
        #if (self.x_val_info is not None):
        #    self.x_val_info['img_file'] = self.x_val_info['img_file'].map(lambda x: Path(Path(dataset_params['val']).parent, x))
        #if (self.x_test_info is not None):
        #    self.x_test_info['img_file'] = self.x_test_info['img_file'].map(lambda x: Path(Path(dataset_params['test']).parent, x))
        #if (self.x_inference_info is not None):
        #    self.x_inference_info['img_file'] = self.x_inference_info['img_file'].map(lambda x: Path(Path(dataset_params['inference']).parent, x))

        # --- load category names ---
        if (Path(dataset.train_dataset['class_name_file_path']).exists()):
            with open(dataset.train_dataset['class_name_file_path'], 'r') as f:
                self.category_names = f.read().splitlines()
        else:
            self.category_names = None

        # --- save config file ---
        configurable_parameters = []
        config_model = {
            'model': configurable_parameters,
        }
        save_config(config_model, self.model_path)

        return
    
    def preprocess_data(self, x):
        """Preprocess Data
        """

        # --- Scaling ---
        x = x.resize(self.input_shape[0:2])

        # --- Normalization ---
        y = np.array(x) / 255.0

        # --- Insert batch dimension ---
        if (len(y.shape) == 3):
            y = np.expand_dims(y, axis=0)

        #return y.tolist()
        return y

    def load_dataset(self):
        """Load Dataset
        
        Load dataset from info and preprocess each samples
        """

        ## --- input tensor ---
        #fn_img2ndarray = lambda x: self.preprocess_data(Image.open(x))
        #if (self.x_train_info is None):
        #    self.x_train = None
        #else:
        #    print('-------------------------------------')
        #    print(f'len(self.x_train_info["img_file"]) = {len(self.x_train_info["img_file"])}')
        #    print('-------------------------------------')
        #    self.x_train = np.array([fn_img2ndarray(x) for x in self.x_train_info['img_file']])
        #    print('-------------------------------------')
        #    print(f'self.x_train.shape =')
        #    print('-------------------------------------')
#
        #if (self.x_val_info is None):
        #    self.x_val = None
        #else:
        #    self.x_val = np.array([fn_img2ndarray(x) for x in self.x_val_info['img_file']])
        #    print('-------------------------------------')
        #    print(f'self.x_val.shape =')
        #    print('-------------------------------------')
#
        #if (self.x_test_info is None):
        #    self.x_test = None
        #else:
        #    #self.x_test = np.array([fn_img2ndarray(x) for x in self.x_test_info['img_file']])
        #    self.x_test = [fn_img2ndarray(x) for x in self.x_test_info['img_file']]
        #    print('-------------------------------------')
        #    print(f'self.x_test.shape =')
        #    print('-------------------------------------')
#
        #if (self.x_inference_info is None): 
        #    self.x_inference = None
        #else:
        #    self.x_inference = np.array([fn_img2ndarray(x) for x in self.x_inference_info['img_file']])
#
        ## --- target ---
        #if (self.y_train_info is None):
        #    self.y_train = None
        #else:
        #    y_list = []
        #    for _target in self.y_train_info['target']:
        #        labels = np.array(_target['class_id'])
        #        xmin = np.array(_target['bbox'][:, 0])
        #        ymin = np.array(_target['bbox'][:, 1])
        #        xmax = np.array(_target['bbox'][:, 0]) + np.array(_target['bbox'][:, 2])
        #        ymax = np.array(_target['bbox'][:, 1]) + np.array(_target['bbox'][:, 3])
        #        valid_targets = np.vstack((xmin, ymin, xmax, ymax, labels)).T
        #        paddings = [[0, 100 - valid_targets.shape[0]], [0, 0]]
        #        y_list.append(np.pad(valid_targets, paddings))
        #    self.y_train = np.array(y_list)
#
        #if (self.y_val_info is None):
        #    self.y_val = None
        #else:
        #    y_list = []
        #    for _target in self.y_val_info['target']:
        #        labels = np.array(_target['class_id'])
        #        xmin = np.array(_target['bbox'][:, 0])
        #        ymin = np.array(_target['bbox'][:, 1])
        #        xmax = np.array(_target['bbox'][:, 0]) + np.array(_target['bbox'][:, 2])
        #        ymax = np.array(_target['bbox'][:, 1]) + np.array(_target['bbox'][:, 3])
        #        valid_targets = np.vstack((xmin, ymin, xmax, ymax, labels)).T
        #        paddings = [[0, 100 - valid_targets.shape[0]], [0, 0]]
        #        y_list.append(np.pad(valid_targets, paddings))
        #    self.y_val = np.array(y_list)
#
        #if (self.y_test_info is None):
        #    self.y_test = None
        #else:
        #    y_list = []
        #    for _target in self.y_test_info['target']:
        #        labels = np.array(_target['class_id'])
        #        xmin = np.array(_target['bbox'][:, 0])
        #        ymin = np.array(_target['bbox'][:, 1])
        #        xmax = np.array(_target['bbox'][:, 0]) + np.array(_target['bbox'][:, 2])
        #        ymax = np.array(_target['bbox'][:, 1]) + np.array(_target['bbox'][:, 3])
        #        valid_targets = np.vstack((xmin, ymin, xmax, ymax, labels)).T
        #        paddings = [[0, 100 - valid_targets.shape[0]], [0, 0]]
        #        y_list.append(np.pad(valid_targets, paddings))
        #    self.y_test = np.array(y_list)
#
        #if (self.y_inference_info is None):
        #    self.y_inference = None
        #else:
        #    y_list = []
        #    for _target in self.y_inference_info['target']:
        #        labels = np.array(_target['class_id'])
        #        xmin = np.array(_target['bbox'][:, 0])
        #        ymin = np.array(_target['bbox'][:, 1])
        #        xmax = np.array(_target['bbox'][:, 0]) + np.array(_target['bbox'][:, 2])
        #        ymax = np.array(_target['bbox'][:, 1]) + np.array(_target['bbox'][:, 3])
        #        valid_targets = np.vstack((xmin, ymin, xmax, ymax, labels)).T
        #        paddings = [[0, 100 - valid_targets.shape[0]], [0, 0]]
        #        y_list.append(np.pad(valid_targets, paddings))
        #    self.y_inference = np.array(y_list)

        return

    def build_model(self):
        """Build Model

        Load YOLOv3 model and load weights from darknet pretrained model
        """
        # --- Load model ---
        self.model = yolov3_models.YoloV3(size=self.input_shape[0], classes=self.class_num, training=True)
        
        # --- Load Darknet pretrined weights ---
        url = 'https://pjreddie.com/media/files/yolov3.weights'
        download_file(url, save_dir='/tmp')
        
        pretrained_model = yolov3_models.YoloV3(size=self.input_shape[0], classes=80, training=True)
        yolov3_load_darknet_weights(pretrained_model, '/tmp/yolov3.weights', False)
        
        self.model.get_layer('yolo_darknet').set_weights(
            pretrained_model.get_layer('yolo_darknet').get_weights())
        yolov3_freeze_all(self.model.get_layer('yolo_darknet'))
        
        self.model.summary()

        return

    def save_model(self):
        """Save Model

        Save trained model
        """

        # --- save model for saved_model ---
        save_path = Path(self.model_path, 'models', 'saved_model')
        os.makedirs(save_path, exist_ok=True)
        self.model.save(save_path)

        # --- save model for h5 ---
        save_path = Path(self.model_path, 'models', 'h5', 'model.h5')
        os.makedirs(Path(self.model_path, 'h5'), exist_ok=True)
        self.model.save(save_path)

        # --- save custom object ---
        #custom_objects = {
        #    'YoloLoss': self.model.loss,
        #}
        #model_dir = Path(self.model_path, 'models')
        #with open(Path(model_dir, 'custom_objects.pickle'), 'wb') as f:
        #    pickle.dump(custom_objects, f)

        return
    
    def load_model(self, trained_model_path):
        """Load Model

        Load trained model

        Args:
            trained_model_path (str) : path to trained model
        """

        #self.model = keras.models.load_model(Path(trained_model_path, 'h5', 'model.h5'))
        #self.model.summary()

        custom_objects = None
        custom_object_path = Path(trained_model_path, 'custom_objects.pickle')
        if (custom_object_path.exists()):
            with open(custom_object_path, 'rb') as f:
                custom_objects = pickle.load(f)
        
        trained_model_path = Path(trained_model_path, 'h5', 'model.h5')
        self.model = keras.models.load_model(trained_model_path, custom_objects=custom_objects)
        self.model.summary()

        return
    
    def train_model(self):
        """Train Model
        """
        # --- compile model ---
        learning_rate = 0.001
        weight_decay = 0.004
        optimizer = tf.keras.optimizers.AdamW(learning_rate=learning_rate, weight_decay=weight_decay)
        metrics = ['accuracy']

        anchors = yolov3_models.yolo_anchors
        anchor_masks = yolov3_models.yolo_anchor_masks
        loss = [yolov3_models.YoloLoss(anchors[mask], classes=self.class_num) for mask in anchor_masks]

        self.model.compile(
            optimizer=optimizer,
            loss=loss,
            metrics=metrics
        )

        # --- callbacks ---
        os.makedirs(Path(self.model_path, 'checkpoints'), exist_ok=True)
        checkpoint_path = Path(self.model_path, 'checkpoints', 'model.ckpt')
        cp_callback = keras.callbacks.ModelCheckpoint(checkpoint_path, save_weights_only=True, verbose=1)
        es_callback = keras.callbacks.EarlyStopping(monitor='val_loss', min_delta=0, patience=5, verbose=1, mode='auto')
        custom_callback = self.CustomCallback(self.trainer_ctrl_fifo)
        tensorboard_logdir = Path(self.model_path, 'logs')
        tensorboard_callback = tf.keras.callbacks.TensorBoard(log_dir=tensorboard_logdir, histogram_freq=1)
        #callbacks = [cp_callback, es_callback]
        callbacks = [cp_callback, custom_callback, tensorboard_callback]

        # --- data augmentation ---
        #datagen = ImageDataGenerator(
        #    rotation_range=0.2,
        #    width_shift_range=0.2,
        #    height_shift_range=0.2,
        #    zoom_range=0.2,
        #    channel_shift_range=0.2,
        #    horizontal_flip=True)
        #datagen.fit(self.x_train)
        
        # --- fit ---
        epochs = 32
        #history = self.model.fit(self.train_dataset,
        #            steps_per_epoch=len(self.x_train)//batch_size, validation_data=self.validation_dataset,
        #            epochs=epochs, callbacks=callbacks,
        #            verbose=0)
        history = self.model.fit(self.train_dataset,
                    validation_data=self.validation_dataset,
                    epochs=epochs, callbacks=callbacks,
                    verbose=0)
        
        # --- Notice the finish training to Web app ---
        if (self.web_app_ctrl_fifo is not None):
            with open(self.web_app_ctrl_fifo, 'w') as f:
                f.write('trainer_done\n')
                
        return

    def predict(self, x, preprocessing=True):
        """Predict

        Predict target from input

        Args:
            x (numpy.ndarray) : input data
            preprocessing (bool) : if nesessary the preprocessing, set to True
        """

        if (preprocessing):
            x = self.preprocess_data(x)
        y = self.model.predict(x)
        
        return y
    
    def decode_prediction(self, pred):
        """Decode Prediction

        Decode prediction to target

        Args:
            pred (numpy.ndarray) : prediction

        Returns:
            numpy.ndarray : target
        """
        def sigmoid(x):
            return 1 / (1 + np.exp(-x))
        
        def yolo_boxes(pred, anchors, classes):
            # pred: (batch_size, grid, grid, anchors, (x, y, w, h, obj, ...classes))
            grid_size = pred.shape[1:3]
            box_xy, box_wh, objectness, class_probs = np.split(pred, (2, 4, 5), axis=-1)
            
            box_xy = sigmoid(box_xy)
            objectness = sigmoid(objectness)
            class_probs = sigmoid(class_probs)
            pred_box = np.concatenate((box_xy, box_wh), axis=-1)  # original xywh for loss

            # !!! grid[x][y] == (y, x)
            grid_x, grid_y = np.meshgrid(np.arange(grid_size[1]), np.arange(grid_size[0]))
            grid = np.stack((grid_x, grid_y), axis=-1)  # [gx, gy, 1, 2]
            grid = np.expand_dims(grid, axis=2)

            box_xy = (box_xy + grid) / np.array(grid_size).reshape(1, 1, 1, 2)
            box_wh = np.exp(box_wh) * anchors

            box_x1y1 = box_xy - box_wh / 2
            box_x2y2 = box_xy + box_wh / 2
            bbox = np.concatenate((box_x1y1, box_x2y2), axis=-1)

            return bbox, objectness, class_probs, pred_box
        
        def yolo_nms(outputs, anchors, masks, classes, yolo_max_boxes=100, yolo_iou_threshold=0.5, yolo_score_threshold=0.5):
            # boxes, conf, type
            b, c, t = [], [], []

            for o in outputs:
                b.append(np.reshape(o[0], (np.shape(o[0])[0], -1, np.shape(o[0])[-1])))
                c.append(np.reshape(o[1], (np.shape(o[1])[0], -1, np.shape(o[1])[-1])))
                t.append(np.reshape(o[2], (np.shape(o[2])[0], -1, np.shape(o[2])[-1])))

            bbox = np.concatenate(b, axis=1)
            confidence = np.concatenate(c, axis=1)
            class_probs = np.concatenate(t, axis=1)

            # If we only have one class, do not multiply by class_prob (always 0.5)
            if classes == 1:
                scores = confidence
            else:
                scores = confidence * class_probs

            dscores = np.squeeze(scores, axis=0)
            scores = np.apply_along_axis(max, 1, dscores)
            bbox = np.reshape(bbox, (-1, 4))
            classes = np.argmax(dscores, axis=1)
            
            final_boxes = cv2.dnn.NMSBoxes(bbox, scores, yolo_score_threshold, yolo_iou_threshold)
            num_valid_nms_boxes = len(final_boxes)
            selected_indices = np.concatenate([final_boxes, np.zeros(yolo_max_boxes - num_valid_nms_boxes)], 0).astype(np.int32)
            
            boxes = np.expand_dims(bbox[selected_indices], axis=0)
            scores = np.expand_dims(scores[selected_indices], axis=0)
            classes = np.expand_dims(classes[selected_indices], axis=0)
            valid_detections = np.expand_dims(num_valid_nms_boxes, axis=0)
            
            return boxes, scores, classes, valid_detections
            
        from machine_learning.lib.trainer.tf_models.yolov3.models import yolo_anchors, yolo_anchor_masks
        
        boxes_0 = yolo_boxes(pred[0], yolo_anchors[yolo_anchor_masks[0]], 20)
        boxes_1 = yolo_boxes(pred[1], yolo_anchors[yolo_anchor_masks[1]], 20)
        boxes_2 = yolo_boxes(pred[2], yolo_anchors[yolo_anchor_masks[2]], 20)
        
        self.prediction = yolo_nms((boxes_0[:3], boxes_1[:3], boxes_2[:3]), yolo_anchors, yolo_anchor_masks, 20)
        boxes, scores, classes, valid_detections = self.prediction
            
        self.decoded_preds['num_detections'] = valid_detections[0]
        self.decoded_preds['detection_boxes'] = np.array(boxes[0][0:valid_detections[0]])[:, [1, 0, 3, 2]]  # [x1, y1, x2, y2]->[y1, x1, y2, x1]
        self.decoded_preds['detection_classes'] = np.array(classes[0][0:valid_detections[0]])
        self.decoded_preds['detection_scores'] = np.array(scores[0][0:valid_detections[0]])

        return self.decoded_preds
    
    def eval_model(self, pred, target):
        """Evaluate Model

        Calculate accuracy score between pred and target

        Args:
            pred (numpy.ndarray): prediction
            target (numpy.ndarray): target
        """

        accuracy = accuracy_score(np.argmax(target, axis=1), np.argmax(pred, axis=1))
        ret = {'accuracy': accuracy}

        return ret
    