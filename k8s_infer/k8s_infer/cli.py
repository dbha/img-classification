####################################################################################################
## The following code is only for functional testing without considering performance and efficiency.
####################################################################################################

import argparse
import click
import os, sys, subprocess
import boto3

from torchvision.io import read_image
from torchvision.models.quantization import resnet50, ResNet50_QuantizedWeights
from torchvision.models.alexnet import alexnet, AlexNet_Weights
from torchvision.models.googlenet import googlenet, GoogLeNet_Weights

import torchvision.models as models
import torch
from PIL import Image
from torchvision import transforms
from efficientnet_pytorch import EfficientNet

from minio import Minio
from minio.error import S3Error


# Check model name validation
def check_pretrained_model(input_model_name):

    # Extract acceptable models
    all_model_names = [name for name in dir(models) if callable(getattr(models, name))]

    # non-model filtering
    all_model_names = [name for name in all_model_names if not name.startswith("__")]

    # Check whether model name is included
    for model_name in all_model_names:
        if model_name.lower() == input_model_name.lower():
            check_result = True
            break
        else:
          check_result = False
        
    return check_result

# Check image file type
def check_file_type(input_image_name):

    # Separate file location and file name
    directory, file_name = os.path.split(input_image_name)
    root, extension = os.path.splitext(file_name)

    if extension in ['.PNG','.JPEG','.png','.jpeg']:
        return True
    else:
        return False

# Deploy on K8s
def deploy_kubernetes(yaml, dict, type):
    try:
        print("Start to deploy workload on Kubernetes")
        subprocess.run(["kubectl", "apply", "-f", yaml], check=True)
        print("Deployment successful!")
    except subprocess.CalledProcessError as e:
        print(f"Error deploying YAML file: {e}")
        sys.exit(0)

# Download image from Object Storage
def download_image_from_minio(endpoint, access_key, secret_key, bucket, bucket_type, yaml, type, workload):

    # There are two main locations to download images from S3.
    # If there is a yaml file, it is called from within the container and the download location is /tmp/container/s3
    # If yaml is blank, it is called from Laptop and the download location is /tmp/local/s3

    try:
       # Connect to MinIO server
        minio_client = Minio(endpoint, access_key, secret_key, secure=False)

        # Get a list of all objects within the MinIO bucket
        objects = minio_client.list_objects(bucket, recursive=True)

        # if type is not None and type.strip() == "Local":
        # When downloading images into Container
        if workload.strip() == "C":
            if bucket_type == 'images':
                local_folder = "/tmp/container/s3/download-s3-images"
            else:
                local_folder = "/tmp/container/s3/imagenet-classes"  
        else:
            # When downloading images using Laptop
            if bucket_type == 'images':
                local_folder = "/tmp/local/s3/download-s3-images"
            else:
                local_folder = "/tmp/local/s3/imagenet-classes"          

        os.makedirs(local_folder, exist_ok=True)
        delete_files_in_directory(local_folder)

        # Download each object and save it locally
        for obj in objects:
            object_name = obj.object_name 
            local_path = os.path.join(local_folder, object_name)

            # Download image from MinIO bucket
            minio_client.fget_object(bucket, object_name, local_path)

            print(f"Downloaded: {object_name} -> {local_path}")
    except S3Error as err:
        print(err)
        sys.exit(1)

# Perform inference after downloading from Object Storage
def inference_s3_image(input_model_name, input_image_name, endpoint, access_key, secret_key, images_bucket, classes_bucket, yaml, s3_dict, type, workload):

    # Deploy Pod via kubectl Download via S3
    if (yaml.strip() != "" and workload.strip() == ""):
        try:
            deploy_kubernetes(yaml, s3_dict, type)
            sys.exit(0)
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

    # Download from deployed container through S3 
    if (yaml.strip() == "" and workload.strip() == "C"):
        try:    
            # Download from container
            download_image_from_minio(endpoint, access_key, secret_key, classes_bucket, 'classes', yaml, type, workload)
            download_image_from_minio(endpoint, access_key, secret_key, images_bucket, 'images', yaml, type, workload)
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
    else:
        # Download from Laptop
        download_image_from_minio(endpoint, access_key, secret_key, classes_bucket, 'classes', yaml, type, workload)
        download_image_from_minio(endpoint, access_key, secret_key, images_bucket, 'images', yaml, type, workload)

    model_class = getattr(models, input_model_name, None)

    print("\n\nmodel_class : ", model_class)
    model = model_class(pretrained=True)
    model.eval()

    preprocess = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    # Import the classes of the ImageNet dataset into the container
    if workload.strip() == "C":
        imagenet_classes_name='/tmp/container/s3/imagenet-classes'
    else:        
        imagenet_classes_name='/tmp/local/s3/imagenet-classes'   

    classes_file_list = os.listdir(imagenet_classes_name)

    for file_name in classes_file_list:
        file_path = os.path.join(imagenet_classes_name, file_name)
        print(file_path)

    # Import image for classification within the container
    if workload.strip() == "C":
        download_images_path_name='/tmp/container/s3/download-s3-images'
    else:
        download_images_path_name='/tmp/local/s3/download-s3-images'
    
    images_file_list = os.listdir(download_images_path_name)

    # Perform inference on images individually
    for image_file_name in images_file_list:
        image_file_path = os.path.join(download_images_path_name, image_file_name)
        print("image_file_path", image_file_path)

        img = Image.open(image_file_path)
        input_tensor = preprocess(img)

        print("input_tensor:\n", input_tensor)
        input_batch = input_tensor.unsqueeze(0)

        # prediction = model(batch).squeeze(0).softmax(0)
        prediction = model(input_batch).squeeze(0).softmax(0)

        # Get a list of classes from the ImageNet dataset
        imagenet_classes_path = file_path
        with open(imagenet_classes_path) as f:
            classes = [line.strip() for line in f.readlines()]

        # Get predicted class ID
        class_id = prediction.argmax().item()
        score = prediction[class_id].item()

        # Output class label
        predicted_class_label = classes[class_id]
        print(f"class id: {predicted_class_label}: {100 * score}%\n")


# Function to infer images stored locally
# Local can be the user's laptop or a container, which can be confirmed through the yaml file
# The image location uses a directory called /tmp/s3 for Container, and /tmp/local directory for user laptop.
# The meaning of using Container in a local environment means that k8s-infer --yaml is inferred by reading the local image through Pod.
def inference_local_image(input_model_name, input_image_name, yaml, local_dict, type):
        
    # There are two types: when the image is directly entered through the input parameter and when the image is saved in a specific location (/tmp/local/existing) on the local laptop.
    # There is a way to read images

    model_class = getattr(models, input_model_name, None)
    print("\n\nmodel_class : ", model_class)

    model = model_class(pretrained=True)   # Create an input model and initialize it using pretrained weights through pretrained parameters.

    model.eval()  # Put the model into inference mode

    # Create a transformation pipeline in which several transformation functions are applied in order to preprocess the image
    preprocess = transforms.Compose([
        transforms.Resize(256),  # Adjust image size
        transforms.CenterCrop(224),
        transforms.ToTensor(),  # Convert image to tensor
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]), # normalization
    ])

    # Inference for one input image
    if input_image_name.strip() != "":

        try:
            img = Image.open(input_image_name)

            input_tensor = preprocess(img)

            print("input_tensor: ", input_tensor)
            input_batch = input_tensor.unsqueeze(0)

            prediction = model(input_batch).squeeze(0).softmax(0)   # Convert the values of the relevant dimension into probability values through softmax
        
            # Get a list of classes from the ImageNet dataset
            imagenet_classes_path = "/tmp/local/existing/imagenet-classes/imagenet_classes.txt" # Download the class list file locally
            with open(imagenet_classes_path) as f:
                classes = [line.strip() for line in f.readlines()]

            # Get predicted class ID
            class_id = prediction.argmax().item()  # Select the class with the highest probability
            score = prediction[class_id].item()

            predicted_class_label = classes[class_id]
            print(f"class id: {predicted_class_label}: {100 * score}%")

        except Exception as e:    
            print(f"\nAn unexpected error occurred: {e}")

    # Read and process the local directory in the container /tmp/local/existing       
    else:
        # Start inference through Container
        if yaml.strip() != "":
            try:
                deploy_kubernetes(yaml, s3_dict, type)
            except Exception as e:
                print(f"An unexpected error occurred: {e}")

# Blank processing for input value None
def process_args(args):
    for key, value in vars(args).items():
        # If value is None, initialized to blank
        setattr(args, key, '' if value is None else value)

def delete_files_in_directory(directory):
    # Get a list of all files in a directory
    file_list = os.listdir(directory)

    # Perform deletion for each file in the directory
    for filename in file_list:
        file_path = os.path.join(directory, filename)
        try:
            if os.path.isfile(file_path):
                # Delete if it is a file
                os.remove(file_path)
            elif os.path.isdir(file_path):
                # If it is a directory, call it recursively to delete the files in the directory
                delete_files_in_directory(file_path)
        except Exception as e:
            print(f"Error deleting {file_path}: {e}")


def main():

    parser = argparse.ArgumentParser(
        description="k8s-infer CLI to demonstrate ml inference leveraging torchvision model"
    )
    parser.add_argument(
        "--models", metavar='model1,model2,model3', type=str,
        help="Input pre-trained Models by Comma-separated values"
    )
    parser.add_argument(
        "--image", type=str,
        help="Input Image Path"
    )
    parser.add_argument(
        "--type", type=str,
        help="Input Local or S3"
    )

    # In case of S3 Option, check parameters
    parser.add_argument(
        "--endpoint", type=str,
        help="Input s3 end_point"
    )
    parser.add_argument(
        "--access_key", type=str,
        help="Input S3 Access key"
    )
    parser.add_argument(
        "--secret_key", type=str,
        help="Input S3 Secret Key"
    )
    parser.add_argument(
        "--images_bucket", type=str,
        help="Input Bucket name where the image is saved"
    )
    parser.add_argument(
        "--classes_bucket", type=str,
        help="Input Bucket name where the classes files is saved"
    ) 
    parser.add_argument(
        "--yaml", type=str,
        help="Enter the yaml path where you want to deploy Kubernetes. \
              In this case, Only the --yaml file path and --type(S3 or Local) option must be used for deployment."
    )
    parser.add_argument(
        "--workload", type=str,
        help="How to get images to make inferences, In this case, default is ' '.", default=""
    ) 
    
    args = parser.parse_args()

    # If the value is None, initialized to blank
    process_args(args)
    
    input_image_name = args.image
    type             = args.type
    endpoint         = args.endpoint
    access_key       = args.access_key
    secret_key       = args.secret_key
    images_bucket    = args.images_bucket
    classes_bucket   = args.classes_bucket
    yaml             = args.yaml
    workload         = args.workload
    
    if args.models:
        # Separate comma separated values into a list
        model_list = args.models.split(',')
    else:
        if yaml.strip() == "":
            print("Please Input input_model_name\n")
            sys.exit(0)

    try:
        # Run Non K8s (Local)
        if yaml.strip() == "":

            # Check the entered Model
            for model_str in model_list:
                # Separate comma separated values into a list
                values = model_str.split(',')

                for input_model_name in values:
                    # Check models and type input
                    check_model=check_pretrained_model(input_model_name)

                    if check_model:
                        # print("valid model : ", input_model_name)
                        print(f"valid model : {input_model_name}")
                    else:
                        # print("invaild model : ", input_model_name)
                        print(f"invaild model : {input_model_name}")
                        sys.exit(0)                

            if type.strip() != "Local" and type.strip() != "S3":
                print("\nPlease Input type only S3 or Local\n")
                sys.exit(0)

            print("type: ", type)

            # Infer images in local directory with k8s-cli
            # The target image to be inferred must be stored in advance locally.
            if type.strip() == "Local":
                # print("\nCall inference_local_image")

                if input_image_name.strip() == "":
                    print("\nPlease Input image path\n")
                    sys.exit(0)

                check_image=check_file_type(input_image_name)
                if check_image:
                    print(f"valid image_type : {input_image_name}\n")
                else:
                    print(f"\ninvaild image_type : {input_image_name}\n")
                    sys.exit(0)
                
                local_dict = {"models_key": input_model_name, "input_image_name_key": input_image_name}

                for model_str in model_list:
                    values = model_str.split(',')
                    for input_model_name in values:
                        inference_local_image(input_model_name, input_image_name, yaml, local_dict, type)

            elif type.strip() == "S3":

                if yaml.strip() == "":
                    if endpoint is None or endpoint.strip() == "":
                        print("\nplease Input endpoint and access_key and secret_key and images_bucket and images_bucket")
                        sys.exit(0)
                    if access_key is None or access_key.strip() == "":
                        print("\nplease Input endpoint and access_key and secret_key and images_bucket and images_bucket")
                        sys.exit(0)                                                                                                       
                    if secret_key is None or secret_key.strip() == "":
                        print("\nplease Input endpoint and access_key and secret_key and images_bucket and images_bucket")
                        sys.exit(0)
                    if images_bucket is None or images_bucket.strip() == "":
                        print("\nplease Input endpoint and access_key and secret_key and images_bucket and images_bucket")
                        sys.exit(0)
                    if classes_bucket is None or classes_bucket.strip() == "":
                        print("\nplease Input endpoint and access_key and secret_key and images_bucket and images_bucket")
                        sys.exit(0)

                    for model_str in model_list:
                        values = model_str.split(',')
                        print(values)

                        for input_model_name in values:
                            s3_dict = {"models_key": input_model_name, "endpoint_key": endpoint, "access_key": access_key, "secret_key": secret_key, "images_bucket_key": images_bucket, "classes_bucket_key": classes_bucket}
                            inference_s3_image(input_model_name, input_image_name, endpoint, access_key, secret_key, images_bucket, classes_bucket, yaml, s3_dict, type, workload)

                else:
                    print(f"invaild type : {type}")
                    sys.exit(0)  
            else:
                print(f"invaild type : {type}")
                sys.exit(0)      

        # Run K8s (Container)        
        else:
            # Use Local Path
            # Infer by reading the laptop image without downloading the image in the container
            # In this case, only S3 is allowed for kubernetes deployment

            if args.models or endpoint.strip() !='' or access_key.strip() !='' or secret_key.strip() !='' or images_bucket !='':
                print("To use kubernetes, Only Input parameter --type --yaml")
                sys.exit(0)

            # Not allowed (only S3) -> PV hostpath and PVC must be utilized
            if type.strip() == "Local":
                print("In the current version, type only allows S3.")
                sys.exit(0)

                # local_dict = {"models_key": input_model_name, "input_image_name_key": input_image_name}
                # inference_local_image(input_model_name, input_image_name, yaml, local_dict, type)

            # After downloading the image within the container, infer by reading the downloaded image
            elif type.strip() == "S3": 
                input_model_name=""  # The model is included in the initialized yaml with blank space.
                s3_dict = {"models_key": "", "endpoint_key": "", "access_key": "", "secret_key": "", "images_bucket_key": "", "classes_bucket_key": ""}
                inference_s3_image(input_model_name, input_image_name, endpoint, access_key, secret_key, images_bucket, classes_bucket, yaml, s3_dict, type, workload)
            else:
                print("Please Check Input type(S3 or Local) Option\n")
                sys.exit(0)

    except Exception as e:    
        print(f"\nAn unexpected error occurred: {e}") 

if __name__ == "__main__":
    main()