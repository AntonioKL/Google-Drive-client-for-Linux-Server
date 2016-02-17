#!/usr/bin/python

import gflags, httplib2, logging, os, sys, re, time

from apiclient.discovery import build
from oauth2client.file import Storage
from oauth2client.client import AccessTokenRefreshError, flow_from_clientsecrets
from oauth2client.tools import run

# Main variables in this code
type_of_the_file='text/plain'
verify_list=[]
temp_verify_list=[]
FLAGS = gflags.FLAGS


#Client Secrets from google API
CLIENT_SECRETS = 'client_secrets.json'

#Error on Client Secrets
MISSING_CLIENT_SECRETS_MESSAGE = """
WARNING: Wrong Authentication 

Please check your file:
   %s

or generate one from <https://code.google.com/apis/console>.

""" % os.path.join(os.path.dirname(__file__), CLIENT_SECRETS)

# Auth Object
FLOW = flow_from_clientsecrets(CLIENT_SECRETS, scope='https://www.googleapis.com/auth/drive', message=MISSING_CLIENT_SECRETS_MESSAGE)

# --help for options 

gflags.DEFINE_enum('logging_level', 'ERROR', ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], 'Set the level of logging detail.')
gflags.DEFINE_string('destination', 'drive_files', 'Destination folder location', short_name='d')
gflags.DEFINE_boolean('debug', False, 'Log folder contents as being fetched' )
gflags.DEFINE_string('logfile', 'drive.log', 'Location of file to write the log' )
gflags.DEFINE_string('drive_id', 'root', 'ID of the folder whose contents are to be fetched' )

def reset_to_zero():
    rest_file = open (FLAGS.destination + "/items", 'w')
    for entry in verify_list:
        str1 = ','.join(entry)
        rest_file.write((str1 + '\n').encode('utf8'))
    rest_file.close()

def get_list_of_old_items():
    verify_file = open (FLAGS.destination + "/items", 'r')
    for raw in verify_file:
        lines = raw[:-1].split(",")
        verify_list.append(lines)
    verify_file.close()

def is_exist(path):
    for entry in verify_list:
        if entry[0] == path:
            entry[1]='1'

def remove_files():
    global verify_list
    if not verify_list:
        rest_file = open (FLAGS.destination + "/items", 'r')
        for raw in rest_file:
            lines = raw[:-1].split(",")
            if lines[1]=='1':
                lines[1] = '0'
                verify_list.append(lines)
        rest_file.close()
    else:
        for entry in reversed(verify_list):
            if entry[1]=="0":
                verify_list.remove(entry)
                if entry[0][-4:] ==".txt" or entry[0][-4:]=='.png' or entry[0][-4:]=='.jpg':
                    os.unlink(entry[0])
                    log( "Removing file: %s" % entry[0] )
                else:
                    os.rmdir(entry[0])
                    log( "Removing Directory: %s" % entry[0] )
            else:
                entry[1]='0'

def create_list_of_items(str):
    item_lists = open (FLAGS.destination + "/items", 'a+')
    if str:
        item_lists.write((str+',1\n').encode('utf8'))
        verify_list.append([str,'1'])
    item_lists.close()

def create_folder():
    FLAGS.destination=FLAGS.destination+"/"
    if not os.path.exists(FLAGS.destination):
        os.makedirs(FLAGS.destination)

def open_logfile():
    if not re.match( '^/', FLAGS.logfile ):
        FLAGS.logfile = FLAGS.destination + FLAGS.logfile
    global LOG_FILE
    LOG_FILE = open( FLAGS.logfile, 'a+' )

def log(str):
    LOG_FILE.write( (time.strftime("%a, %d %b %Y %H:%M:%S") + '\t' + str + '\n').encode('utf8') )
    print (time.strftime("%a, %d %b %Y %H:%M:%S") + '\t' + str).encode('utf8')

def ensure_dir(directory):
    if not os.path.exists(directory):
        log( "Created Directory: %s" % directory)
        os.makedirs(directory)
        create_list_of_items(directory)
    is_exist(directory)

def is_google_doc(drive_file):
    return True if re.match( '^application/vnd\.google-apps\..+', drive_file['mimeType'] ) else False

def is_file_modified(drive_file, local_file):
    is_exist(local_file)
    if os.path.exists( local_file ):
        rtime = time.mktime( time.strptime( drive_file['modifiedDate'], '%Y-%m-%dT%H:%M:%S.%fZ' ) )
        ltime = os.path.getmtime( local_file )
        return rtime > ltime
    else:
        return True

def get_folder_contents( service, http, folder, base_path='./', depth=0 ):
    if FLAGS.debug:
        log( "\n" + '  ' * depth + "Getting contents of folder %s" % folder['title'] )
    try:
        folder_contents = service.files().list( q="'%s' in parents and trashed=false" % folder['id'] ).execute()
    except:
        log( "ERROR: Couldn't get contents of folder %s. Retrying..." % folder['title'] )
        get_folder_contents( service, http, folder, base_path, depth )
        return
    folder_contents = folder_contents['items']
    dest_path = base_path + folder['title'].replace( '/', '_' ) + '/'

    def is_file(item):
        return item['mimeType'] != 'application/vnd.google-apps.folder'

    def is_folder(item):
        return item['mimeType'] == 'application/vnd.google-apps.folder'

    if FLAGS.debug:
        for item in folder_contents:
            if is_folder( item ):
                log( '  ' * depth + "[] " + item['title'] )
            else:
                log( '  ' * depth + "-- " + item['title'] )

    ensure_dir( dest_path )

    for item in filter(is_file, folder_contents):
        ending='.txt'
        if item['title'].replace( '/', '_' )[-4:]=='.png' or item['title'].replace( '/', '_' )[-4:]=='.jpg':
            ending=''

        full_path = dest_path + item['title'].replace( '/', '_' ) + ending
        if is_file_modified( item, full_path ):
            is_file_new = not os.path.exists( full_path )
            if download_file( service, item, dest_path ):
                if is_file_new:
                    log( "Created %s" % full_path )
                    create_list_of_items(full_path)
                else:
                    log( "Updated %s" % full_path )
            else:
                log( "ERROR while saving %s" % full_path )

    for item in filter(is_folder, folder_contents):
        get_folder_contents( service, http, item, dest_path, depth+1 )

def download_file( service, drive_file, dest_path ):
    ending='.txt'
    if drive_file['title'][-4:]=='.png' or drive_file['title'][-4:]=='.jpg':
        ending=''

    file_location = dest_path + drive_file['title'].replace( '/', '_' ) + ending

    if is_google_doc(drive_file):
        download_url = drive_file['exportLinks']['%s' % type_of_the_file]
    else:
        download_url = drive_file['downloadUrl']
    if download_url:
        try:
            resp, content = service._http.request(download_url)
        except httplib2.IncompleteRead:
            log( 'Error while reading file %s. Retrying...' % drive_file['title'].replace( '/', '_' ) )
            download_file( service, drive_file, dest_path )
            return False
        if resp.status == 200:
            try:
                target = open( file_location, 'w+' )
            except:
                log( "Could not open file %s for writing. Please check permissions." % file_location )
                return False
            target.write( content )
            return True
        else:
            log( 'An error occurred: %s' % resp )
            return False
    else:
        # The file doesn't have any content stored on Drive.
        return False

def main(argv):
    # Let the gflags module process the command-line arguments
    try:
        argv = FLAGS(argv)
    except gflags.FlagsError, e:
        print '%s\\nUsage: %s ARGS\\n%s' % (e, argv[0], FLAGS)
        sys.exit(1)

    # Set the logging
    logging.getLogger().setLevel(getattr(logging, FLAGS.logging_level))

    # If the Credentials don't exist or are invalid run through the native client
    # flow. The Storage object will ensure that if successful the good
    # Credentials will get written back to a file.
    storage = Storage('drive.dat')
    credentials = storage.get()
    if credentials is None or credentials.invalid:
        credentials = run(FLOW, storage)

    create_folder()
    open_logfile()

    # Create an httplib2.Http object to handle our HTTP requests and authorize it
    # with the good Credentials.
    http = httplib2.Http()
    http = credentials.authorize(http)
    try:
        service = build("drive", "v2", http=http)
    except:
        log("==Can't reach Google, check your Internet==")
        sys.exit()

    create_list_of_items('')
    get_list_of_old_items()
    
    try:
        start_folder = service.files().get( fileId=FLAGS.drive_id ).execute()
        get_folder_contents( service, http, start_folder, FLAGS.destination )
    except AccessTokenRefreshError:
        #print ("The credentials have been revoked or expired, please re-run the application to re-authorize")
        log("The credentials have been revoked or expired, please re-run the application to re-authorize")
        sys.exit()

    verify_list.sort(lambda x,y: cmp(len(x[0]), len(y[0])))
    remove_files()
    reset_to_zero()

if __name__ == '__main__':
    main(sys.argv)

