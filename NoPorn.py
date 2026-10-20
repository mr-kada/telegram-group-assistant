from nsfw_detector import predict

# Load the pre-trained model
model = predict.load_model("nsfw.299x299.h5")


# Check if the image is NSFW (porn or sexy > 0.7 threshold)
def is_nsfw_image(image_path):
    result = predict.classify(model, image_path)
    print(result)
    # nsfw_score = result[image_path].get('porn', 0) + result[image_path].get('sexy', 0)
    # return nsfw_score > 0.7

print(is_nsfw_image('welcomeMessage_media/photo_2025-03-05_02-56-46.jpg'))  # True or False

# Example usage
# print(is_image_porn('welcomeMessage_media/photo_2025-03-05_02-56-46.jpg'))
# print(is_video_porn('video.mp4'))  # Replace with an actual video filename
