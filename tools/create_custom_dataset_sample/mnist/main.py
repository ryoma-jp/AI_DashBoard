#! -*- coding: utf-8 -*-

#---------------------------------
# モジュールのインポート
#---------------------------------
import os
import argparse
import json
import pickle
import cv2
import numpy as np
import pandas as pd

#---------------------------------
# 定数定義
#---------------------------------

#---------------------------------
# 関数
#---------------------------------
def ArgParser():
	parser = argparse.ArgumentParser(description='MNISTデータセットをAI Dashboardのカスタムデータセットの形式に変換する',
				formatter_class=argparse.RawTextHelpFormatter)

	# --- 引数を追加 ---
	parser.add_argument('--input_dir', dest='input_dir', type=str, default='input', required=False, \
			help='MNISTデータセットのディレクトリパス')
	parser.add_argument('--output_dir', dest='output_dir', type=str, default='output', required=False, \
			help='カスタムデータセットの出力ディレクトリ')
	parser.add_argument('--n_data', dest='n_data', type=int, default=0, required=False, \
			help='取得するデータサンプル数(0以下指定で全データを取得)')

	args = parser.parse_args()

	return args

def load_mnist_dataset(input_dir):
	# --- load training data ---
	f = open(os.path.join(input_dir, 'train-images-idx3-ubyte'))
	byte_data = np.fromfile(f, dtype=np.uint8)
	
	n_items = (byte_data[4] << 24) | (byte_data[5] << 16) | (byte_data[6] << 8) | (byte_data[7])
	img_h = (byte_data[8] << 24) | (byte_data[9] << 16) | (byte_data[10] << 8) | (byte_data[11])
	img_w = (byte_data[12] << 24) | (byte_data[13] << 16) | (byte_data[14] << 8) | (byte_data[15])
	train_images = byte_data[16:].reshape(n_items, img_h, img_w)
	
	# --- load training label ---
	f = open(os.path.join(input_dir, 'train-labels-idx1-ubyte'))
	byte_data = np.fromfile(f, dtype=np.uint8)
	n_items = (byte_data[4] << 24) | (byte_data[5] << 16) | (byte_data[6] << 8) | (byte_data[7])
	train_labels = byte_data[8:]
	
	# --- load test data ---
	f = open(os.path.join(input_dir, 't10k-images-idx3-ubyte'))
	byte_data = np.fromfile(f, dtype=np.uint8)
	
	n_items = (byte_data[4] << 24) | (byte_data[5] << 16) | (byte_data[6] << 8) | (byte_data[7])
	img_h = (byte_data[8] << 24) | (byte_data[9] << 16) | (byte_data[10] << 8) | (byte_data[11])
	img_w = (byte_data[12] << 24) | (byte_data[13] << 16) | (byte_data[14] << 8) | (byte_data[15])
	test_images = byte_data[16:].reshape(n_items, img_h, img_w)
	
	# --- load test label ---
	f = open(os.path.join(input_dir, 't10k-labels-idx1-ubyte'))
	byte_data = np.fromfile(f, dtype=np.uint8)
	n_items = (byte_data[4] << 24) | (byte_data[5] << 16) | (byte_data[6] << 8) | (byte_data[7])
	test_labels = byte_data[8:]
	
	return train_images, train_labels, test_images, test_labels
	
def save_image_files(images, image_shape, labels, output_dir, name='images', n_data=0):
	dict_image_file = {
		'id': [],
		'file': [],
		'class_id': [],
	}
	
	os.makedirs(os.path.join(output_dir, name), exist_ok=True)
	
	if ((n_data <= 0) or (n_data > len(images))):
		n_data = len(images)
		
	for i, (image, label) in enumerate(zip(images[0:n_data], labels[0:n_data])):
		image_file = os.path.join(name, f'{i:08}.png')
		image = image.reshape(image_shape)
		cv2.imwrite(os.path.join(output_dir, image_file), image)
		
		dict_image_file['id'].append(i)
		dict_image_file['file'].append(image_file)
		# dict_image_file['class_id'].append(int(np.argmax(label)))
		dict_image_file['class_id'].append(int(label))
		
	# --- save image files information to json file ---
	df_image_file = pd.DataFrame(dict_image_file)
	with open(os.path.join(output_dir, 'info.json'), 'w') as f:
		json.dump(json.loads(df_image_file.to_json(orient='records')), f, ensure_ascii=False, indent=4)
	
	return None
	
def main():
	# --- 引数処理 ---
	args = ArgParser()
	print('args.input_dir : {}'.format(args.input_dir))
	print('args.output_dir : {}'.format(args.output_dir))
	print('args.n_data : {}'.format(args.n_data))
	
	# --- MNISTデータセット読み込み ---
	train_images, train_labels, test_images, test_labels = load_mnist_dataset(args.input_dir)
	
	# --- save image files(train) ---
	output_dir = os.path.join(args.output_dir, 'train_data')
	os.makedirs(output_dir, exist_ok=True)
	save_image_files(train_images, train_images.shape[1:], train_labels, output_dir, name='images', n_data=args.n_data)
	
	# --- save image files(test) ---
	output_dir = os.path.join(args.output_dir, 'test_data')
	os.makedirs(output_dir, exist_ok=True)
	save_image_files(test_images, test_images.shape[1:], test_labels, output_dir, name='images', n_data=args.n_data)
	
	return

#---------------------------------
# メイン処理
#---------------------------------
if __name__ == '__main__':
	main()

