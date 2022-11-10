import argparse
import os
import glob
import random
from tkinter import Y
import darknet
import time
import cv2
import numpy as np
import darknet


def parser():
    parser = argparse.ArgumentParser(description="YOLO Object Detection")
    parser.add_argument("--input", type=str, default="",
                        help="image source. It can be a single image, a"
                        "txt with paths to them, or a folder. Image valid"
                        " formats are jpg, jpeg or png."
                        "If no input is given, ")
    parser.add_argument("--batch_size", default=1, type=int,
                        help="number of images to be processed at the same time")
    parser.add_argument("--weights", default="../training/yolov4-custom_best.weights",
                        help="yolo weights path")
    parser.add_argument("--dont_show", action='store_true',
                        help="windown inference display. For headless systems")
    parser.add_argument("--ext_output", action='store_true',
                        help="display bbox coordinates of detected objects")
    parser.add_argument("--save_labels", action='store_true',
                        help="save detections bbox for each image in yolo format")
    parser.add_argument("--config_file", default="./cfg/yolov4-custom.cfg",
                        help="path to config file")
    parser.add_argument("--data_file", default="./data/obj.data",
                        help="path to data file")
    parser.add_argument("--thresh", type=float, default=.6,
                        help="remove detections with lower confidence")
    return parser.parse_args()


def check_arguments_errors(args):
    assert 0 < args.thresh < 1, "Threshold should be a float between zero and one (non-inclusive)"
    if not os.path.exists(args.config_file):
        raise(ValueError("Invalid config path {}".format(os.path.abspath(args.config_file))))
    if not os.path.exists(args.weights):
        raise(ValueError("Invalid weight path {}".format(os.path.abspath(args.weights))))
    if not os.path.exists(args.data_file):
        raise(ValueError("Invalid data file path {}".format(os.path.abspath(args.data_file))))
    if args.input and not os.path.exists(args.input):
        raise(ValueError("Invalid image path {}".format(os.path.abspath(args.input))))


def check_batch_shape(images, batch_size):
    """
        Image sizes should be the same width and height
    """
    shapes = [image.shape for image in images]
    if len(set(shapes)) > 1:
        raise ValueError("Images don't have same shape")
    if len(shapes) > batch_size:
        raise ValueError("Batch size higher than number of images")
    return shapes[0]


def load_images(images_path):
    """
    If image path is given, return it directly
    For txt file, read it and return each line as image path
    In other case, it's a folder, return a list with names of each
    jpg, jpeg and png file
    """
    input_path_extension = images_path.split('.')[-1]
    if input_path_extension in ['jpg', 'jpeg', 'png']:
        return [images_path]
    elif input_path_extension == "txt":
        with open(images_path, "r") as f:
            return f.read().splitlines()
    else:
        return glob.glob(
            os.path.join(images_path, "*.jpg")) + \
            glob.glob(os.path.join(images_path, "*.png")) + \
            glob.glob(os.path.join(images_path, "*.jpeg"))


def prepare_batch(images, network, channels=3):
    width = darknet.network_width(network)
    height = darknet.network_height(network)

    darknet_images = []
    for image in images:
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image_resized = cv2.resize(image_rgb, (width, height),
                                   interpolation=cv2.INTER_LINEAR)
        custom_image = image_resized.transpose(2, 0, 1)
        darknet_images.append(custom_image)

    batch_array = np.concatenate(darknet_images, axis=0)
    batch_array = np.ascontiguousarray(batch_array.flat, dtype=np.float32)/255.0
    darknet_images = batch_array.ctypes.data_as(darknet.POINTER(darknet.c_float))
    return darknet.IMAGE(width, height, channels, darknet_images)


def image_detection(image_path, network, class_names, class_colors, thresh):
    # Darknet doesn't accept numpy images.
    # Create one with image we reuse for each detect
    width = darknet.network_width(network)
    height = darknet.network_height(network)
    darknet_image = darknet.make_image(width, height, 3)

    image = cv2.imread(image_path)
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    image_resized = cv2.resize(image_rgb, (width, height),
                               interpolation=cv2.INTER_LINEAR)

    darknet.copy_image_from_bytes(darknet_image, image_resized.tobytes())
    detections = darknet.detect_image(network, class_names, darknet_image, thresh=thresh)
    darknet.free_image(darknet_image)
    image = darknet.draw_boxes(detections, image_resized, class_colors)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB), detections


def batch_detection(network, images, class_names, class_colors,
                    thresh=0.25, hier_thresh=.5, nms=.45, batch_size=4):
    image_height, image_width, _ = check_batch_shape(images, batch_size)
    darknet_images = prepare_batch(images, network)
    batch_detections = darknet.network_predict_batch(network, darknet_images, batch_size, image_width,
                                                     image_height, thresh, hier_thresh, None, 0, 0)
    batch_predictions = []
    for idx in range(batch_size):
        num = batch_detections[idx].num
        detections = batch_detections[idx].dets
        if nms:
            darknet.do_nms_obj(detections, num, len(class_names), nms)
        predictions = darknet.remove_negatives(detections, class_names, num)
        images[idx] = darknet.draw_boxes(predictions, images[idx], class_colors)
        batch_predictions.append(predictions)
    darknet.free_batch_detections(batch_detections, batch_size)
    return images, batch_predictions


def image_classification(image, network, class_names):
    width = darknet.network_width(network)
    height = darknet.network_height(network)
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    image_resized = cv2.resize(image_rgb, (width, height),
                                interpolation=cv2.INTER_LINEAR)
    darknet_image = darknet.make_image(width, height, 3)
    darknet.copy_image_from_bytes(darknet_image, image_resized.tobytes())
    detections = darknet.predict_image(network, darknet_image)
    predictions = [(name, detections[idx]) for idx, name in enumerate(class_names)]
    darknet.free_image(darknet_image)
    return sorted(predictions, key=lambda x: -x[1])


def convert2relative(image, bbox):
    """
    YOLO format use relative coordinates for annotation
    """
    x, y, w, h = bbox
    height, width, _ = image.shape
    return x/width, y/height, w/width, h/height


def save_annotations(name, image, detections, class_names):
    """
    Files saved with image_name.txt and relative coordinates
    """
    file_name = os.path.splitext(name)[0] + ".txt"
    with open(file_name, "w") as f:
        for label, confidence, bbox in detections:
            x, y, w, h = convert2relative(image, bbox)
            label = class_names.index(label)
            f.write("{} {:.4f} {:.4f} {:.4f} {:.4f} {:.4f}\n".format(label, x, y, w, h, float(confidence)))

def batch_detection_example():
    args = parser()
    check_arguments_errors(args)
    batch_size = 3
    random.seed(3)  # deterministic bbox colors
    network, class_names, class_colors = darknet.load_network(
        args.config_file,
        args.data_file,
        args.weights,
        batch_size=batch_size
    )
    image_names = ['data/horses.jpg', 'data/horses.jpg', 'data/eagle.jpg']
    images = [cv2.imread(image) for image in image_names]
    images, detections,  = batch_detection(network, images, class_names,
                                           class_colors, batch_size=batch_size)
    for name, image in zip(image_names, images):
        cv2.imwrite(name.replace("data/", ""), image)
    print(detections)

def uniquify(path):
    filename, extension = os.path.splitext(path)
    counter = 1

    while os.path.exists(path):
        path = filename + " (" + str(counter) + ")" + extension
        counter += 1

    return path

def main():
    args = parser()
    check_arguments_errors(args)

    random.seed(3)  # deterministic bbox colors
    network, class_names, class_colors = darknet.load_network(
        args.config_file,
        args.data_file,
        args.weights,
        batch_size=args.batch_size
    )

    images = load_images(args.input)

    index = 0
    while True:
        # loop asking for new image paths if no list is given
        if args.input:
            if index >= len(images):
                break
            image_name = images[index]
        else:
            image_name = input("Enter Image Path: ")
        prev_time = time.time()
        image, detections = image_detection(
            image_name, network, class_names, class_colors, args.thresh
            )
        if args.save_labels:
            save_annotations(image_name, image, detections, class_names)
        darknet.print_detections(detections, args.ext_output)
        # print("---------------------------DETEKSI MANTAP----------------------------------------")
        # print(detections)
        # print(type(detections))

        # truckodolInfo = ''

        # for item in detections:
        #     if item[0] == 'truk_odol':
        #         truckodolInfo = item

        # print(truckodolInfo)
        # print(type(truckodolInfo))

        # xmin = int(truckodolInfo[2][0] - truckodolInfo[2][2]/2)
        # xmax = int(truckodolInfo[2][0] + truckodolInfo[2][2]/2)

        # ymin = int(truckodolInfo[2][1] - truckodolInfo[2][3]/2)
        # ymax = int(truckodolInfo[2][1] + truckodolInfo[2][3]/2)

        # truckodol_image = image[ymin:ymax,xmin:xmax]

        # print(type(image))

        # cv2.imshow('ENAK',truckodol_image)
        # cv2.waitKey(0)
        # cv2.destroyAllWindows()

        # defaultpath = '../cropimage_gambar/cropodol.png'

        # checkpath = uniquify(defaultpath)

        # jos = cv2.imwrite(checkpath,truckodol_image)

        # print("Image written to file-system : ",jos)


        # print("---------------------------DETEKSI MANTAP----------------------------------------")
        savepath = uniquify("../save_image/yolov4.jpg")
        jos2 = cv2.imwrite(savepath, image)
        print("Image written to file-system : ",jos2)



        fps = int(1/(time.time() - prev_time))
        print("FPS: {}".format(fps))
        if not args.dont_show:
            cv2.rectangle(image,(0,0), (250,90), (0, 0, 0), -1)
            cv2.putText(image, ("koor roda depan : ({:.0f},{:.0f}) ".format(float(detections[0][2][0]),float(detections[0][2][1]))), (10,20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,255,255), 1)
            if len(detections) <= 2:
                cv2.putText(image, "Error", (10,60), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,0,0), 1)
            elif len(detections) == 3:
                cv2.putText(image, ("koor roda belakang : ({:.0f},{:.0f}) ".format(float(detections[1][2][0]),float(detections[1][2][1]))), (10,40), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,255,255), 1)
                cv2.putText(image, ("truk terdeteksi sebagai {} ".format(detections[2][0])), (10,60), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,255,255), 1)
                bumperD = (detections[2][2][0])-(detections[2][2][2]/2)
                bumperB = (detections[2][2][0])+(detections[2][2][2]/2)
                foh = (detections[0][2][0]) - bumperD
                roh = bumperB - (detections[1][2][0])
                sumbu = (detections[1][2][0])-(detections[0][2][0])
                if((foh<=0.475*sumbu) and (roh<=0.625*sumbu)):
                    cv2.putText(image, "Chassis legal", (10,80), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,255,255), 1)
                else: 
                    cv2.putText(image, "Chassis illegal", (10,80), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,255,255), 1)
                parameterD = 0.475*sumbu
                parameterB = 0.625*sumbu
                print("Bumper depan = ",bumperD)
                print("FOH = ", foh)
                print("Bumper belakang = ", bumperB)
                print("ROH = ",roh)
                print("Jarak sumbu = ",sumbu)
                print("Parameter Depan = ", parameterD)
                print("Parameter Belakang = ", parameterB)
                
            elif len(detections) == 4:
                cv2.putText(image, ("koor roda belakang : ({:.0f},{:.0f}) ".format(float(detections[2][2][0]),float(detections[2][2][1]))), (10,40), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,255,255), 1)
                cv2.putText(image, ("truk terdeteksi sebagai {} ".format(detections[3][0])), (10,60), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,255,255), 1)
                bumperD = (detections[3][2][0])-(detections[3][2][2]/2)
                bumperB = (detections[3][2][0])+(detections[3][2][2]/2)
                foh = (detections[0][2][0]) - bumperD
                roh = bumperB - (detections[2][2][0])
                sumbu = (detections[2][2][0])-(detections[0][2][0])
                if((foh<=0.475*sumbu) and (roh<=0.625*sumbu)):
                    cv2.putText(image, "Chassis legal", (10,80), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,255,255), 1)
                else: 
                    cv2.putText(image, "Chassis illegal", (10,80), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,255,255), 1)
                parameterD = 0.475*sumbu
                parameterB = 0.625*sumbu
                print("Bumper depan = ",bumperD)
                print("FOH = ", foh)
                print("Bumper belakang = ", bumperB)
                print("ROH = ",roh)
                print("Jarak sumbu = ",sumbu)
                print("Parameter Depan = ", parameterD)
                print("Parameter Belakang = ", parameterB)

            elif len(detections) == 5:
                cv2.putText(image, ("koor roda belakang : ({:.0f},{:.0f}) ".format(float(detections[3][2][0]),float(detections[3][2][1]))), (10,40), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,255,255), 1)
                cv2.putText(image, ("truk terdeteksi sebagai {} ".format(detections[4][0])), (10,60), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,255,255), 1)
            else:
                cv2.putText(image, "Error", (10,60), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,0,0), 1)
            cv2.imshow('Inference', image)
            savepath = uniquify("../save_image/yolov4.jpg")
            jos3 = cv2.imwrite(savepath, image)
            print("Image written to file-system : ",jos3)
            if cv2.waitKey() & 0xFF == ord('q'):
                break
        index += 1


if __name__ == "__main__":
    # unconmment next line for an example of batch processing
    # batch_detection_example()
    main()