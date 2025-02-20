import os
import pandas as pd
import numpy as np
from tqdm import tqdm
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import confusion_matrix, accuracy_score, recall_score, f1_score
import catboost as ctb
import argparse
from imblearn.over_sampling import SMOTE


def create_features(path_dataset, num_frames):
    games = os.listdir(path_dataset)
    # games.remove('Readme.docx')
    df = pd.DataFrame()
    for game in tqdm(games):
        clips = os.listdir(os.path.join(path_dataset, game))
        for clip in clips:
            labels = pd.read_csv(os.path.join(path_dataset, game, clip, 'Label.csv'))

            eps = 1e-8  # Nhỏ để tránh chia cho 0

            for i in range(1, num_frames):
                # Tạo độ trễ cho tọa độ x, y
                labels['x_lag_{}'.format(i)] = labels['x-coordinate'].shift(i)
                labels['x_lag_inv_{}'.format(i)] = labels['x-coordinate'].shift(-i)
                labels['y_lag_{}'.format(i)] = labels['y-coordinate'].shift(i)
                labels['y_lag_inv_{}'.format(i)] = labels['y-coordinate'].shift(-i)
                
                # Tạo sự khác biệt giữa tọa độ hiện tại và tọa độ ở khung trước
                labels['x_diff_{}'.format(i)] = abs(labels['x_lag_{}'.format(i)] - labels['x-coordinate'])
                labels['y_diff_{}'.format(i)] = labels['y_lag_{}'.format(i)] - labels['y-coordinate']
                labels['x_diff_inv_{}'.format(i)] = abs(labels['x_lag_inv_{}'.format(i)] - labels['x-coordinate'])
                labels['y_diff_inv_{}'.format(i)] = labels['y_lag_inv_{}'.format(i)] - labels['y-coordinate']
                
                # Phép chia giữa x_diff và x_diff_inv
                labels['x_div_{}'.format(i)] = abs(labels['x_diff_{}'.format(i)] / (labels['x_diff_inv_{}'.format(i)] + eps))
                labels['y_div_{}'.format(i)] = labels['y_diff_{}'.format(i)] / (labels['y_diff_inv_{}'.format(i)] + eps)

                # Tạo độ trễ cho thời gian
                labels['t_lag_{}'.format(i)] = labels['time stamp'].shift(i)
                labels['t_diff_{}'.format(i)] = labels['time stamp'] - labels['t_lag_{}'.format(i)]
                
                # Tính vận tốc (velocity) theo trục x và y
                labels['v_x_{}'.format(i)] = labels['x_diff_{}'.format(i)] / (labels['t_diff_{}'.format(i)] + eps)
                labels['v_y_{}'.format(i)] = labels['y_diff_{}'.format(i)] / (labels['t_diff_{}'.format(i)] + eps)
                
                # Tính vận tốc ngược (velocity_inv) theo trục x và y
                labels['t_lag_inv_{}'.format(i)] = labels['time stamp'].shift(-i)
                labels['t_diff_inv_{}'.format(i)] = labels['t_lag_inv_{}'.format(i)] - labels['time stamp']
                
                labels['v_x_inv_{}'.format(i)] = labels['x_diff_inv_{}'.format(i)] / (labels['t_diff_inv_{}'.format(i)] + eps)
                labels['v_y_inv_{}'.format(i)] = labels['y_diff_inv_{}'.format(i)] / (labels['t_diff_inv_{}'.format(i)] + eps)
                
                # Tính gia tốc (acceleration) theo trục x và y
                labels['a_x_{}'.format(i)] = (labels['v_x_{}'.format(i)] - labels['v_x_inv_{}'.format(i)]) / (labels['t_diff_{}'.format(i)] + eps)
                labels['a_y_{}'.format(i)] = (labels['v_y_{}'.format(i)] - labels['v_y_inv_{}'.format(i)]) / (labels['t_diff_{}'.format(i)] + eps)


            labels['target'] = (labels['status'] == 2).astype(int)         
            for i in range(1, num_frames):    
                labels = labels[labels['x_lag_{}'.format(i)].notna()]
                labels = labels[labels['x_lag_inv_{}'.format(i)].notna()]
            labels = labels[labels['x-coordinate'].notna()]  

            labels['status'] = labels['status'].astype(int)
            df = pd.concat([df, labels], ignore_index=True)
    return df

def create_train_test(df, num_frames):
    colnames_x = ['x_diff_{}'.format(i) for i in range(1, num_frames)] + \
                 ['x_diff_inv_{}'.format(i) for i in range(1, num_frames)] + \
                 ['x_div_{}'.format(i) for i in range(1, num_frames)]
    colnames_y = ['y_diff_{}'.format(i) for i in range(1, num_frames)] + \
                 ['y_diff_inv_{}'.format(i) for i in range(1, num_frames)] + \
                 ['y_div_{}'.format(i) for i in range(1, num_frames)]
    colnames_z = ['v_x_{}'.format(i) for i in range(1, num_frames)] + \
                 ['v_y_{}'.format(i) for i in range(1, num_frames)] + \
                 ['v_x_inv_{}'.format(i) for i in range(1, num_frames)] + \
                 ['v_y_inv_{}'.format(i) for i in range(1, num_frames)] + \
                 ['a_x_{}'.format(i) for i in range(1, num_frames)] + \
                 ['a_y_{}'.format(i) for i in range(1, num_frames)] 
    colnames = colnames_x + colnames_y + colnames_z
    df_train, df_test = train_test_split(df, test_size=0.25, random_state=7)
    X_train = df_train[colnames]
    X_test = df_test[colnames]
    y_train = df_train['target']
    y_test = df_test['target']

    # Over sampling TP
    smote = SMOTE(random_state=42)
    X_train_balanced, y_train_balanced = smote.fit_resample(X_train, y_train)
    return X_train_balanced, y_train_balanced, X_test, y_test


if __name__ == '__main__':
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--path_dataset', type=str, help='path to the TrackNet dataset')
    parser.add_argument('--path_save_model', type=str, help='path for saving model with .cbm format')
    args = parser.parse_args()    
    
    NUM_FEATURE_FRAMES = 3
    df_features = create_features(args.path_dataset, NUM_FEATURE_FRAMES)
    X_train, y_train, X_test, y_test = create_train_test(df_features, NUM_FEATURE_FRAMES)
    
    train_dataset = ctb.Pool(X_train, y_train)
    model_ctb = ctb.CatBoostRegressor(loss_function='RMSE')
    grid = {'iterations': [100, 200, 500],
            'learning_rate': [0.03, 0.1],
            'depth': [2, 4, 6, 8],
            'l2_leaf_reg': [0.2, 0.5, 1, 3]}
    model_ctb.grid_search(grid, train_dataset)
    
    df_features.head()

    pred_ctb = model_ctb.predict(X_test)
    y_pred_bin = (pred_ctb > 0.45).astype(int)
    
    tn, fp, fn, tp = confusion_matrix(y_test, y_pred_bin).ravel()
    print(f"Number of rows in X_test: {len(X_test)}")
    print(f"Number of rows in y_test: {len(y_test)}")

    print('tn = {}, fp = {}, fn = {}, tp = {}'.format(tn, fp, fn, tp))
    print('accuracy = {}'.format(accuracy_score(y_test, y_pred_bin)))
    print('recall = {}'.format(recall_score(y_test, y_pred_bin)))
    print('f1 score = {}'.format(f1_score(y_test, y_pred_bin)))
    
    model_ctb.save_model(args.path_save_model)
