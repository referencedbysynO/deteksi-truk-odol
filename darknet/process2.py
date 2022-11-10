import glob, os

# Current directory
current_dir = os.path.dirname(os.path.abspath(__file__))

print(current_dir)

current_dir = 'data/ghmendungwithCutout'

# Percentage of images to be used for the test set
percentage_test = 100;

# Create and/or truncate train.txt and test.txt
file_train = open('data/trainghmendung.txt', 'w')
file_test = open('data/ghmendungwithCutout.txt', 'w')

# Populate train.txt and test.txt
counter = 1
index_test = round(100 / percentage_test)
for pathAndFilename in glob.iglob(os.path.join(current_dir, "*.jpg")):
    title, ext = os.path.splitext(os.path.basename(pathAndFilename))

    if counter == index_test:
        counter = 1
        file_test.write("data/ghmendungwithCutout" + "/" + title + '.jpg' + "\n")
    else:
        file_train.write("data/ghmendungwithCutout" + "/" + title + '.jpg' + "\n")
        counter = counter + 1