"""Unpack upload archive into source directory for analysis.

Upload archive may contain other tarred/gzipped archives internally.

"""

# TODO Compress - Need to implement uncompress for traditional Unix compress .Z files.
#      Need to figure best way to shell/system out to system uncompress program since
#      this is not supported directly in Python.

import shutil
import os.path

import tarfile
import zipfile

from filemanager.arXiv.File import File

from filemanager.process.sanitize import Upload

ERROR_MSG_PRE = 'There were problems unpacking "'
ERROR_MSG_SUF = '" -- continuing. Please try again and confirm your files.'

# TODO Add logging so we are able to capture additional information during
# debugging - for now deactivate
DEBUG = 0


def unpack_archive(upload: Upload):
    """Uppack specified archive and recursively traverse the source directory
    and unpack any additional
       gzipped/tar archives contained in original archive."""

    #archive_name = os.path.basename(archive_path)
    # TODO debug logging ("*******Process upload: " + archive_name + '*****************')

    source_directory = upload.get_source_directory()
    removed_directory = upload.get_removed_directory()

    # Recursively scan source directory and uplack all archives until there
    # are no more gzipped/tar archives.
    packed_file = 1
    round = 1
    while packed_file:
        # TODO debug logging ("\n*****ROUND " + str(round) + '  Packed: '
        # + str(packed_file) + '*****\n')

        for root_directory, directories, files in os.walk(source_directory):
            # TODO debug logging (f"---> Dir {root_directory} contains the
            # directories {b} and the files {c}")
            for file in files:

                # os.walk provides a list of files with the root directory so
                # we need to build path at each step
                path = os.path.join(root_directory, file)

                # wrap in our File encapsulation class
                obj = File(path, source_directory)

                # TODO log something to source log
                # print("File is : " + file + " Size: " + str(obj.size)
                # + " File is type: " + obj.type + ":" + obj.type_string + '\n')

                # Tar module is supposed to handle bz2 compressed files (gzip too)
                if ((obj.type == 'tar' or obj.type == 'gzipped')
                        and tarfile.is_tarfile(path)) or obj.type == 'bzip2':
                    # TODO debug logging ("**Found tar  or bzip2 file!**\n")

                    target_directory = os.path.join(source_directory, root_directory)

                    try:
                        tar = tarfile.open(path)
                    except tarfile.TarError as error:
                        # Do something better with as error
                        upload.add_warning("There were problems opening file '"
                                           + obj.public_filepath + "'")
                        upload.add_warning('Tar error message: ' + error.__str__())

                    try:
                        for tarinfo in tar:
                            # print("Tar name: " + tarinfo.name() + '\n')
                            # print("**" + tarinfo.name, "is", tarinfo.size,
                            #     "bytes in size and is", end="")

                            # TODO: Need to think about this a little more.
                            # Don't really want to flatten directory structure,
                            # but not sure we can just secure basename.
                            # secure = secure_filename(tarinfo.name)
                            # if (secure != tarinfo.name):
                            #    print("\nFile name not secure: " + tarinfo.name
                            #        + ' (' + secure + ')\n')

                            # if tarinfo.name.startswith('.'):
                            # These get handled in checks and logged.

                            # Extract files and directories for now
                            if tarinfo.isreg():
                                # log this? ("Reg File")
                                tar.extract(tarinfo, target_directory)
                            elif tarinfo.isdir():
                                # log this? ("Dir")
                                tar.extract(tarinfo, target_directory)
                            else:
                                # Warn about entities we don't want to see in
                                # upload archives
                                # We did not check carefully in legacy system
                                # and hard links caused bad things to happen.
                                if tarinfo.issym():  # sym link
                                    upload.add_warning("Symbolic links are not allowed. Removing '"
                                                       + tarinfo.name + "'.")
                                elif tarinfo.islnk():  # hard link
                                    upload.add_warning('Hard links are not allowed. Removing ')
                                elif tarinfo.ischr():
                                    upload.add_warning('Hard links are not allowed. Removing ')
                                elif tarinfo.isblk():
                                    upload.add_warning('Block devices are not allowed. Removing ')
                                elif tarinfo.isfifo():
                                    upload.add_warning('FIFO are not allowed. Removing ')
                                elif tarinfo.isdev():
                                    upload.add_warning('Character devices are '
                                                       + 'not allowed. Removing ')
                        tar.close()

                    except tarfile.TarError as error:
                        # TODO: Do something with as error, post to error log
                        # print("Error processing tar file failed!\n")
                        upload.add_warning(ERROR_MSG_PRE + obj.public_filepath + ERROR_MSG_SUF)
                        upload.add_warning('Tar error message: ' + error.__str__())

                    # Move gzipped file out of way
                    rfile = os.path.join(removed_directory, os.path.basename(path))

                    # Maybe can't do this in production if submitter reloads tar.gz
                    if os.path.exists(rfile) and (os.path.getsize(rfile) == os.path.getsize(path)):
                        print("File (same size) saved already! Remove tar file")
                        os.remove(path)
                    else:
                        rem_path = os.path.join(removed_directory, os.path.basename(path))
                        # TODO: debugging log ("Moving tar file to removed dir: " + rem_path)
                        shutil.move(path, rem_path)
                    # Since we are unpacking something we want to make one more pass over files.
                    packed_file += 1
                elif obj.type == 'tar' and not tarfile.is_tarfile(path):
                    print("Package 'tarfile' unable to read this tar file.")
                    # TODO Throw and error

                # Hanlde .zip files
                elif obj.type == 'zip' and zipfile.is_zipfile(path):
                    print("*******Process zip archive: " + path)
                    try:
                        with zipfile.ZipFile(path, "r") as zip_ref:
                            zip_ref.extractall(source_directory)
                            rem_path = os.path.join(removed_directory, os.path.basename(path))
                            # TODO: debug logging ("Moving zip file to removed dir: " + rem_path)
                            shutil.move(path, rem_path)
                            # Since we are unpacking something we want to make
                            # one more pass over files.
                            packed_file += 1
                    except zipfile.BadZipFile as error:
                        # TODO: Think about warnings a bit. Tar/zip problems
                        # currently reported as warnings. Upload warnings allow
                        # submitter to continue on to process/compile step.
                        upload.add_warning(ERROR_MSG_PRE + obj.public_filepath + ERROR_MSG_SUF)
                        upload.add_warning('Zip error message: ' + error.__str__())

                # TODO: Add support for compressed files
                elif obj.type == 'compressed':
                    print("We can't uncompress .Z files yet.")

                # TODO: Handle 'processed' and __MACOSX directories (removal of/deletion)

                # TODO: Handle encrypted files - need to investigate Crypt and how we are using it.

        round += 1
        packed_file -= 1

    # Set permissions on all directories and files
    for root_directory, directories, files in os.walk(source_directory):
        for file in files:
            file_path = os.path.join(root_directory, file)
            os.chmod(file_path, 0o664)
        for dir in directories:
            dir_path = os.path.join(root_directory, dir)
            os.chmod(dir_path, 0o775)
