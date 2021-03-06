import rospy
from nav_msgs.msg import Odometry
from nav_msgs.msg import OccupancyGrid
from sensor_msgs.msg import LaserScan
from tf.transformations import euler_from_quaternion
from geometry_msgs.msg import Twist
import math
from math import pi
import cmath
import numpy as np
import time
import cv2
from sound_play.msg import SoundRequest
from sound_play.libsoundplay import SoundClient
#import random

laser_range = np.array([])
occdata = np.array([])
yaw = 0.0
rotate_speed = 0.1
linear_speed = 0.1
stop_distance = 0.35
occ_bins = [-1, 0, 100, 101]
front_angle = 30
front_angles = range(-front_angle,front_angle+1,1)
rotated = Image.fromarray(np.array(np.zeros((1,1))))

def get_odom_dir(msg):
    global yaw

    orientation_quat =  msg.pose.pose.orientation
    orientation_list = [orientation_quat.x, orientation_quat.y, orientation_quat.z, orientation_quat.w]
    (roll, pitch, yaw) = euler_from_quaternion(orientation_list)


def get_laserscan(msg):
    global laser_range

    # create numpy array
    laser_range = np.array(msg.ranges)
    # replace 0's with nan's
    # could have replaced all values below msg.range_min, but the small values
    # that are not zero appear to be useful
    laser_range[laser_range==0] = np.nan


def get_occupancy(msg):
    global occdata
    global rotated

    # create numpy array
    occdata = np.array([msg.data])
    # compute histogram to identify percent of bins with -1
    occ_counts = np.histogram(occdata,occ_bins)
    # calculate total number of bins
    total_bins = msg.info.width * msg.info.height
    # log the info
    rospy.loginfo('Width: %i Height: %i',msg.info.width,msg.info.height)
    rospy.loginfo('Unmapped: %i Unoccupied: %i Occupied: %i Total: %i', occ_counts[0][0], occ_counts[0][1], occ_counts[0][2], total_bins)

    # find transform to convert map coordinates to base_link coordinates
    # lookup_transform(target_frame, source_frame, time)
    trans = tfBuffer.lookup_transform('map', 'base_link', rospy.Time(0))
    cur_pos = trans.transform.translation
    cur_rot = trans.transform.rotation
    rospy.loginfo(['Trans: ' + str(cur_pos)])
    rospy.loginfo(['Rot: ' + str(cur_rot)])

    # get map resolution
    map_res = msg.info.resolution
    # get map origin struct has fields of x, y, and z
    map_origin = msg.info.origin.position
    # get map grid positions for x, y position
    grid_x = round((cur_pos.x - map_origin.x) / map_res)
    grid_y = round(((cur_pos.y - map_origin.y) / map_res))
    rospy.loginfo(['Grid Y: ' + str(grid_y) + ' Grid X: ' + str(grid_x)])

    # make occdata go from 0 instead of -1, reshape into 2D
    oc2 = occdata + 1
    # set all values above 1 (i.e. above 0 in the original map data, representing occupied locations)
    oc3 = (oc2>1).choose(oc2,2)
    # reshape to 2D array using column order
    odata = np.uint8(oc3.reshape(msg.info.height,msg.info.width,order='F'))
    # set current robot location to 0
    odata[grid_x][grid_y] = 0
    # create image from 2D array using PIL
    img = Image.fromarray(odata.astype(np.uint8))
    # find center of image
    i_centerx = msg.info.width/2
    i_centery = msg.info.height/2
    # translate by curr_pos - centerxy to make sure the rotation is performed
    # with the robot at the center
    # using tips from:
    # https://stackabuse.com/affine-image-transformations-in-python-with-numpy-pillow-and-opencv/
    translation_m = np.array([[1, 0, (i_centerx-grid_y)],
                               [0, 1, (i_centery-grid_x)],
                               [0, 0, 1]])
    # Image.transform function requires the matrix to be inverted
    tm_inv = np.linalg.inv(translation_m)
    # translate the image so that the robot is at the center of the image
    img_transformed = img.transform((msg.info.height, msg.info.width),
                                    Image.AFFINE,
                                    data=tm_inv.flatten()[:6],
                                    resample=Image.NEAREST)

    # convert quaternion to Euler angles
    orientation_list = [cur_rot.x, cur_rot.y, cur_rot.z, cur_rot.w]
    (roll, pitch, yaw) = euler_from_quaternion(orientation_list)
    rospy.loginfo(['Yaw: R: ' + str(yaw) + ' D: ' + str(np.degrees(yaw))])

    # rotate by 180 degrees to invert map so that the forward direction is at the top of the image
    rotated = img_transformed.rotate(np.degrees(-yaw)+180)
    # we should now be able to access the map around the robot by converting
    # back to a numpy array: im2arr = np.array(rotated)

    # show image using grayscale map
    plt.imshow(rotated,cmap='gray')
    plt.draw_all()
    # pause to make sure the plot gets created
    plt.pause(0.00000000001)

def rotatebot(rot_angle):
    global yaw

    # create Twist object
    twist = Twist()
    # set up Publisher to cmd_vel topic
    pub = rospy.Publisher('cmd_vel', Twist, queue_size=10)
    # set the update rate to 1 Hz
    rate = rospy.Rate(1)

    # get current yaw angle
    current_yaw = np.copy(yaw)
    # log the info
    rospy.loginfo(['Current: ' + str(math.degrees(current_yaw))])
    # we are going to use complex numbers to avoid problems when the angles go from
    # 360 to 0, or from -180 to 180
    c_yaw = complex(math.cos(current_yaw),math.sin(current_yaw))
    # calculate desired yaw
    target_yaw = current_yaw + math.radians(rot_angle)
    # convert to complex notation
    c_target_yaw = complex(math.cos(target_yaw),math.sin(target_yaw))
    rospy.loginfo(['Desired: ' + str(math.degrees(cmath.phase(c_target_yaw)))])
    # divide the two complex numbers to get the change in direction
    c_change = c_target_yaw / c_yaw
    # get the sign of the imaginary component to figure out which way we have to turn
    c_change_dir = np.sign(c_change.imag)
    # set linear speed to zero so the TurtleBot rotates on the spot
    twist.linear.x = 0.0
    # set the direction to rotate
    twist.angular.z = c_change_dir * rotate_speed
    # start rotation
    pub.publish(twist)

    # we will use the c_dir_diff variable to see if we can stop rotating
    c_dir_diff = c_change_dir
    # rospy.loginfo(['c_change_dir: ' + str(c_change_dir) + ' c_dir_diff: ' + str(c_dir_diff)])
    # if the rotation direction was 1.0, then we will want to stop when the c_dir_diff
    # becomes -1.0, and vice versa
    while(c_change_dir * c_dir_diff > 0):
        # get current yaw angle
        current_yaw = np.copy(yaw)
        # get the current yaw in complex form
        c_yaw = complex(math.cos(current_yaw),math.sin(current_yaw))
        rospy.loginfo('While Yaw: %f Target Yaw: %f', math.degrees(current_yaw), math.degrees(target_yaw))
        # get difference in angle between current and target
        c_change = c_target_yaw / c_yaw
        # get the sign to see if we can stop
        c_dir_diff = np.sign(c_change.imag)
        # rospy.loginfo(['c_change_dir: ' + str(c_change_dir) + ' c_dir_diff: ' + str(c_dir_diff)])
        angle_to_go = abs(target_yaw - current_yaw)
        twist.linear.x = 0.0
        twist.angular.z = c_change_dir * rotate_speed * (angle_to_go/pi)
        pub.publish(twist)
        rate.sleep()

    rospy.loginfo(['End Yaw: ' + str(math.degrees(current_yaw))])
    # set the rotation speed to 0
    twist.angular.z = 0.0
    # stop the rotation
    time.sleep(1)
    pub.publish(twist)

def direction_to_go(rotated):
    pixels=np.array(rotated)
    lst=[]
    angle=set()
    i_centerx=msg.info.width/2
    i_centery=msg.info.height/2
    for y in range(msg.info.height):
            for x in range(msg.info.width):
                    if pixels[y][x]==0:
                            lst.append([x-i_centerx,i_centery-y])
    b=np.array([0,0])
    c=np.array([0,1])
    for i in lst:
            a=np.array(i)
            ba = a - b
            bc = c - b
            cosine_angle = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc))
            angle1 = np.arccos(cosine_angle)*(180/pi)
            if a[0]>0:
                    angle.add(-int(angle1))
            else:
                    angle.add(int(angle1))
    return(angle)

def pick_direction():
    global laser_range
    
    # publish to cmd_vel to move TurtleBot
    pub = rospy.Publisher('cmd_vel', Twist, queue_size=10)

    # stop moving
    twist = Twist()
    twist.linear.x = 0.0
    twist.angular.z = 0.0
    time.sleep(1)
    pub.publish(twist)
    
    get_possible=list(filter(lambda x:x>stop_distance,laser_scan))
    possible=[]
    for i in get_possible:
        possible.append(laser_scan.index(i))

    #get the angle to go
    target_direction=direction_to_go(rotated)
    direction=list(target_direction & possible)

    # randomly pick a target
    target=random.choice(tuple(direction))

    # rotate to that direction
    rotatebot(target)
    
    while laser_range > stop_distance:
        # start moving
        rospy.loginfo(['Start moving'])
        twist.linear.x = linear_speed
        twist.angular.z = 0.0
        # not sure if this is really necessary, but things seem to work more
        # reliably with this
        time.sleep(1)
        pub.publish(twist)
        
    #stop moving when the robot's 0 deg is less than stop_distance
    twist.liner.x = 0.0
    twist.angular.z = 0.0
    time.sleep(1)
    pub.publish(twist)


def stopbot():
    # publish to cmd_vel to move TurtleBot
    pub = rospy.Publisher('cmd_vel', Twist, queue_size=10)

    twist = Twist()
    twist.linear.x = 0.0
    twist.angular.z = 0.0
    time.sleep(1)
    pub.publish(twist)


def closure(mapdata):
    # This function checks if mapdata contains a closed contour. The function
    # assumes that the raw map data from SLAM has been modified so that
    # -1 (unmapped) is now 0, and 0 (unoccupied) is now 1, and the occupied
    # values go from 1 to 101.

    # According to: https://stackoverflow.com/questions/17479606/detect-closed-contours?rq=1
    # closed contours have larger areas than arc length, while open contours have larger
    # arc length than area. But in my experience, open contours can have areas larger than
    # the arc length, but closed contours tend to have areas much larger than the arc length
    # So, we will check for contour closure by checking if any of the contours
    # have areas that are more than 10 times larger than the arc length
    # This value may need to be adjusted with more testing.
    ALTHRESH = 10
    # We will slightly fill in the contours to make them easier to detect
    DILATE_PIXELS = 3

    # assumes mapdata is uint8 and consists of 0 (unmapped), 1 (unoccupied),
    # and other positive values up to 101 (occupied)
    # so we will apply a threshold of 2 to create a binary image with the
    # occupied pixels set to 255 and everything else is set to 0
    # we will use OpenCV's threshold function for this
    ret,img2 = cv2.threshold(mapdata,2,255,0)
    # we will perform some erosion and dilation to fill out the contours a
    # little bit
    element = cv2.getStructuringElement(cv2.MORPH_CROSS,(DILATE_PIXELS,DILATE_PIXELS))
    # img3 = cv2.erode(img2,element)
    img4 = cv2.dilate(img2,element)
    # use OpenCV's findContours function to identify contours
    # OpenCV version 3 changed the number of return arguments, so we
    # need to check the version of OpenCV installed so we know which argument
    # to grab
    fc = cv2.findContours(img4, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    (major, minor, _) = cv2.__version__.split(".")
    if(major == '3'):
        contours = fc[1]
    else:
        contours = fc[0]
    # find number of contours returned
    lc = len(contours)
    # rospy.loginfo('# Contours: %s', str(lc))
    # create array to compute ratio of area to arc length
    cAL = np.zeros((lc,2))
    for i in range(lc):
        cAL[i,0] = cv2.contourArea(contours[i])
        cAL[i,1] = cv2.arcLength(contours[i], True)

    # closed contours tend to have a much higher area to arc length ratio,
    # so if there are no contours with high ratios, we can safely say
    # there are no closed contours
    cALratio = cAL[:,0]/cAL[:,1]
    # rospy.loginfo('Closure: %s', str(cALratio))
    if np.any(cALratio > ALTHRESH):
        return True
    else:
        return False

def occupancy():
    # initialize node
    rospy.init_node('occupancy', anonymous=True)

    tfBuffer = tf2_ros.Buffer()
    tfListener = tf2_ros.TransformListener(tfBuffer)
    rospy.sleep(1.0)

    # subscribe to map occupancy data
    rospy.Subscriber('map', OccupancyGrid, get_occupancy, tfBuffer)

    plt.ion()
    plt.show()

    # spin() simply keeps python from exiting until this node is stopped
    rospy.spin()

def mover():
    global laser_range

    occupancy()

    rospy.init_node('mover', anonymous=True)

    # subscribe to odometry data
    rospy.Subscriber('odom', Odometry, get_odom_dir)
    # subscribe to LaserScan data
    rospy.Subscriber('scan', LaserScan, get_laserscan)
    # subscribe to map occupancy data
    rospy.Subscriber('map', OccupancyGrid, get_occupancy)

    rospy.on_shutdown(stopbot)

    rate = rospy.Rate(5) # 5 Hz

    # save start time
    start_time = time.time()
    # initialize variable to write elapsed time to file
    contourCheck = 1

    # find direction with the largest distance from the Lidar,
    # rotate to that direction, and start moving
    pick_direction()

    while not rospy.is_shutdown():
        if laser_range.size != 0:
            # check distances in front of TurtleBot and find values less
            # than stop_distance
            lri = (laser_range[front_angles]<float(stop_distance)).nonzero()
            rospy.loginfo('Distances: %s', str(lri))
        else:
            lri[0] = []

        # if the list is not empty
        if(len(lri[0])>0):
            rospy.loginfo(['Stop!'])
            # find direction with the largest distance from the Lidar
            # rotate to that direction
            # start moving
            pick_direction()

        # check if SLAM map is complete
        if contourCheck :
            if closure(occdata) :
                # map is complete, so save current time into file
                with open("maptime.txt", "w") as f:
                    f.write("Elapsed Time: " + str(time.time() - start_time))
                contourCheck = 0
                # play a sound
                soundhandle = SoundClient()
                rospy.sleep(1)
                soundhandle.stopAll()
                soundhandle.play(SoundRequest.NEEDS_UNPLUGGING)
                rospy.sleep(2)
                # save the map
                cv2.imwrite('mazemap.png',occdata)

        rate.sleep()


if __name__ == '__main__':
    try:
        mover()
    except rospy.ROSInterruptException:
        pass
