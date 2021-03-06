#!/usr/bin/env python

"""
   Persistent caching FUSE filesystem

   Copyright 2012 Jonny Tyers

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

"""

import os
import pickle
import signal
import stat
# We explicitly refer to __builtin__ here so it can be mocked
import __builtin__

from pprint import pformat

import fuse

import vfs
from ranges import (Ranges, Range)
from pcachefsutil import debug, is_read_only_flags
from pcachefsutil import E_PERM_DENIED, E_NOT_IMPL


fuse.fuse_python_api = (0, 2)


class FuseStat(fuse.Stat):
    """Convenient class for Stat objects.

    Set up the stat object based on values from the given stat object
    (which should come from os.stat()).
    """
    def __init__(self, st):
        fuse.Stat.__init__(self)

        self.st_mode = st.st_mode
        self.st_nlink = st.st_nlink
        self.st_size = st.st_size
        self.st_atime = st.st_atime
        self.st_mtime = st.st_mtime
        self.st_ctime = st.st_ctime

        self.st_dev = st.st_dev
        self.st_gid = st.st_gid
        self.st_ino = st.st_ino
        self.st_uid = st.st_uid

        self.st_rdev = st.st_rdev
        self.st_blksize = st.st_blksize

    def __repr__(self):
        v = vars(self)
        v['is_dir'] = stat.S_ISDIR(v['st_mode'])
        v['is_char_dev'] = stat.S_ISCHR(v['st_mode'])
        v['is_block_dev'] = stat.S_ISBLK(v['st_mode'])
        v['is_file'] = stat.S_ISREG(v['st_mode'])
        v['is_fifo'] = stat.S_ISFIFO(v['st_mode'])
        v['is_symlk'] = stat.S_ISLNK(v['st_mode'])
        v['is_sock'] = stat.S_ISSOCK(v['st_mode'])
        return pformat(v)


class PersistentCacheFs(fuse.Fuse):
    """Main FUSE class

    This just delegates operations to a Cacher instance.
    """
    def __init__(self, *args, **kw):
        fuse.Fuse.__init__(self, *args, **kw)

        # Currently we have to run in single-threaded mode to prevent
        # the cache becoming corrupted
        self.parse(['-s'])

        self.parser.add_option('-c', '--cache-dir', dest='cache_dir', help="Specifies the directory where cached data should be stored. This will be created if it does not exist.")
        self.parser.add_option('-t', '--target-dir', dest='target_dir', help="The directory which we are caching. The content of this directory will be mirrored and all reads cached.")
        self.parser.add_option('-v', '--virtual-dir', dest='virtual_dir', help="The folder in the mount dir in which the virtual filesystem controlling pcachefs will reside.")

        self.cache_dir = None
        self.target_dir = None
        self.virtual_dir = None
        self.cacher = None
        self.vfs = None

    def main(self, args=None):
        options = self.cmdline[0]

        if options.cache_dir is None:
            self.parser.error('Need to specify --cache-dir')
        if options.target_dir is None:
            self.parser.error('Need to specify --target-dir')

        self.cache_dir = options.cache_dir
        self.target_dir = options.target_dir
        self.virtual_dir = options.virtual_dir or '.pcachefs'

        self.cacher = Cacher(self.cache_dir, UnderlyingFs(self.target_dir))
        self.vfs = vfs.VirtualFS(self.virtual_dir, self.cacher)

        signal.signal(signal.SIGINT, signal.SIG_DFL)
        fuse.Fuse.main(self, args)

    def getattr(self, path):
        debug('PersistentCacheFs.getattr', path)
        if self.vfs.contains(path):
            return self.vfs.getattr(path)

        return self.cacher.getattr(path)

    def readdir(self, path, offset):
        debug('PersistentCacheFs.readdir', path, offset)
        for f in self.vfs.readdir(path, offset):
            if f is None:
                return
            yield f

        for f in self.cacher.readdir(path, offset):
            yield f

    def open(self, path, flags):
        debug('PersistentCacheFs.open', path, flags)
        if self.vfs.contains(path):
            return self.vfs.open(path, flags)

        if not is_read_only_flags(flags):
            return E_PERM_DENIED

        return 0

    def read(self, path, size, offset):
        debug('PersistentCacheFs.read', path, size, offset)
        if self.vfs.contains(path):
            return self.vfs.read(path, size, offset)

        return self.cacher.read(path, size, offset)

    def truncate(self, path, size):
        debug('PersistentCacheFs.truncate', path, size)
        if self.vfs.contains(path):
            return self.vfs.truncate(path, size)

        return E_NOT_IMPL

    def write(self, path, buf, offset):
        debug('PersistentCacheFs.write', path, buf, offset)
        if self.vfs.contains(path):
            return self.vfs.write(path, buf, offset)

        return E_NOT_IMPL

    def flush(self, path):
        debug('PersistentCacheFs.flush', path)
        if self.vfs.contains(path):
            return self.vfs.flush(path)

        return 0 # success

    def release(self, path, what):
        debug('PersistentCacheFs.release', path, what)
        if self.vfs.contains(path):
            return self.vfs.release(path)

        return 0 # success

#    def _getattr_special(self, path):
#        return FuseStat(os.stat('/proc/version')) # FIXME stat of the FUSE mountpoint
#
#    def _read_special(self, path, size, offset):
#        debug("_read_special", path, size, offset)
#        content = None
#
#        if path == self.CACHE_ONLY_MODE_PATH:
#            debug("_read_special com", path, size, offset)
#            if self.cacher.cache_only_mode == True:
#                debug(" return 1")
#                return '111111111111111111111111111\n'[offset:offset+size]
#            else:
#                debug(" return 0")
#                return '000000000000000000000000000\n'[offset:offset+size]
#
#        else:
#            debug(" return NSF")
#            return E_NO_SUCH_FILE
#
#    def _write_special(self, path, buf, offset):
#        content = buf.strip()
#        debug("_write_special", path, buf, offset)
#
#        if path == self.CACHE_ONLY_MODE_PATH:
#            if content == '0':
#                self.cacher.cache_only_mode = False
#                return len(buf) # wrote one byte
#
#            elif content == '1':
#                self.cacher.cache_only_mode = True
#                return len(buf) # wrote one byte
#
#            else:
#                return self.E_INVAL
#
#        else:
#            return E_NO_SUCH_FILE

class UnderlyingFs(object):
    """Implementation of FUSE operations that fetches data from the underlying FS."""
    def __init__(self, real_path):
        self.real_path = real_path

    def _get_real_path(self, path):
        if path[0] != '/':
            raise ValueError("Expected leading slash")

        return os.path.join(self.real_path, path[1:])

    def getattr(self, path):
        debug('UnderlyingFs.getattr', path)
        return FuseStat(os.stat(self._get_real_path(path)))

    def readdir(self, path, offset):
        debug('UnderlyingFs.readdir', path, offset)
        real_path = self._get_real_path(path)

        dirents = []
        if os.path.isdir(real_path):
            dirents.extend([ '.', '..' ])

        dirents.extend(os.listdir(real_path))

        # return a generator over the entries in the directory
        return (fuse.Direntry(r) for r in dirents)

    def read(self, path, size, offset):
        debug('UnderlyingFs.read', path, size, offset)
        real_path = self._get_real_path(path)

        with __builtin__.open(real_path, 'rb') as f:
            f.seek(offset)
            result = f.read(size)

        return result


class Cacher(object):
    """
    Represents a cache, which caches entire files and their content.
    This class mimics the interface of a python Fuse object.

    The cache is a standard filesystem directory.

    Initially the implementation will copy *entire* files (incl
    metadata) down into the cache when they are read.

    The cached files are stored as follows in the cache directory:
      /cache/dir/filename.ext/cache.data   # copy of file data
      /cache/dir/filename.ext/cache.stat  # pickle'd stat object (from os.stat())
      /cache/dir/cache.list # pickle'd directory listing (from os.listdir())

    For writes to files in the cache, these are passed through to the
    underlying filesystem without any caching.
    """

    def __init__(self, cachedir, underlying_fs):
        """
        Initialise a new Cacher.

        cachedir the directory in which to store cached files and
        metadata (this will created automatically if it does not exist)
        underlying_fs an object supporting the read(), readdir() and
        getattr() FUSE operations. For any files/dirs not in the cache,
        this object's methods will be called to retrieve the real data
        and populate the cache.
        """
        self.cachedir = cachedir
        self.underlying_fs = underlying_fs

        # If this is set to True, the cacher will fail if any
        # requests are made for data that does not exist in the cache
        self.cache_only_mode = False


        if not os.path.exists(self.cachedir):
            self._mkdir(self.cachedir)

    def cache_only_mode_enable(self):
        debug('Cacher.cache_only_mode_enable')
        self.cache_only_mode = True

    def cache_only_mode_disable(self):
        debug('Cacher.cache_only_mode_disable')
        self.cache_only_mode = False

    def get_cached_blocks(self, path):
        data_cache_range = self._get_cache_dir(path, 'cache.data.range')

        cached_blocks = None
        if os.path.exists(data_cache_range):
            with __builtin__.open(data_cache_range, 'rb') as f:
                cached_blocks = pickle.load(f)
        else:
            cached_blocks = Ranges()

        return cached_blocks

    def update_cached_blocks(self, path, cached_blocks):
        data_cache_range = self._get_cache_dir(path, 'cache.data.range')

        with __builtin__.open(data_cache_range, 'wb') as f:
            pickle.dump(cached_blocks, f)

    def remove_cached_blocks(self, path):
        data_cache_range = self._get_cache_dir(path, 'cache.data.range')

        os.remove(data_cache_range)

    def get_cached_data(self, path, size, offset):
        cache_data = self._get_cache_dir(path, 'cache.data')

        result = None
        with __builtin__.open(cache_data, 'rb') as f:
            f.seek(offset)
            result = f.read(size)

        return result

    def init_cached_data(self, path):
        cache_data = self._get_cache_dir(path, 'cache.data')

        if os.path.exists(cache_data):
            return

        file_stat = self.getattr(path)
        self._create_cache_dir(path)

        with __builtin__.open(cache_data, 'wb') as f:
            f.truncate()
            f.seek(file_stat.st_size - 1)
            f.write('\0')

    def update_cached_data(self, path, blocks_to_read):
        if not blocks_to_read:
            return

        cache_data = self._get_cache_dir(path, 'cache.data')

        # Now open it up in update mode so we can add data to it as
        # we read the data from the underlying filesystem
        with __builtin__.open(cache_data, 'r+b') as cache_data_file:

            # Now loop through all the blocks we need to get
            # and append them to the cached file as we go
            for block in blocks_to_read:
                block_data = self.underlying_fs.read(path, block.size, block.start)

                cache_data_file.seek(block.start)
                cache_data_file.write(block_data) # overwrites existing data in the file

    def remove_cached_data(self, path):
        data_cache = self._get_cache_dir(path, 'cache.data')
        os.remove(data_cache)

        data_cache_range = self._get_cache_dir(path, 'cache.data.range')
        os.remove(data_cache_range)

    def read(self, path, size, offset, force_reload=False):
        """Read the given data from the given path on the filesystem.

        Any parts which are requested and are not in the cache are read
        from the underlying filesystem
        """
        debug('Cacher.read', path, size, offset)

        self.init_cached_data(path)

        if force_reload:
            self.remove_cached_blocks(path)

        cached_blocks = self.get_cached_blocks(path)
        blocks_to_read = cached_blocks.get_uncovered_portions(Range(offset, offset+size))

        self.update_cached_data(path, blocks_to_read)
        self.update_cached_blocks(path, cached_blocks.add_ranges(blocks_to_read))

        return self.get_cached_data(path, size, offset)


    def readdir(self, path, offset):
        """List the given directory, from the cache."""
        debug('Cacher.readdir', path, offset)
        cache_dir = self._get_cache_dir(path, 'cache.list')

        result = None
        if os.path.exists(cache_dir):
            with __builtin__.open(cache_dir, 'rb') as list_cache_file:
                result = pickle.load(list_cache_file)

        else:
            result_generator = self.underlying_fs.readdir(path, offset)
            result = list(result_generator)

            self._create_cache_dir(path)
            with __builtin__.open(cache_dir, 'wb') as list_cache_file:
                pickle.dump(result, list_cache_file)

        # Return a new generator over our list of items
        return (x for x in result)

    def getattr(self, path):
        """Retrieve stat information for a particular file from the cache."""
        debug('Cacher.getattr', path)
        cache_dir = self._get_cache_dir(path, 'cache.stat')

        result = None
        if os.path.exists(cache_dir):
            with __builtin__.open(cache_dir, 'rb') as stat_cache_file:
                result = pickle.load(stat_cache_file)

        else:
            result = self.underlying_fs.getattr(path)

            self._create_cache_dir(path)
            with __builtin__.open(cache_dir, 'wb') as stat_cache_file:
                pickle.dump(result, stat_cache_file)

        return result

    def write(self, path, buf, offset):  # pylint: disable=no-self-use
        debug('Cacher.write', path, buf, offset)
        return E_NOT_IMPL

    def _get_cache_dir(self, path, file = None):
        """For a given path, return the name of the directory used to cache data for that path."""
        if path[0] != '/':
            raise ValueError("Expected leading slash")

        if file is None:
            return os.path.join(self.cachedir, path[1:])

        return os.path.join(self.cachedir, path[1:], file)

    def _create_cache_dir(self, path):
        """Create the cache path for the given directory if it does not already exist."""
        cache_dir = self._get_cache_dir(path)
        self._mkdir(cache_dir)

    def _mkdir(self, path):  # pylint: disable=no-self-use
        """Create the given directory if it does not already exist."""
        if not os.path.exists(path):
            os.makedirs(path)


def main(args=None):
    usage="""
    pCacheFS: A persistently caching filesystem.
    """ + fuse.Fuse.fusage

    version = "%prog " + fuse.__version__

    server = PersistentCacheFs(version=version, usage=usage, dash_s_do='setsingle')

    parsed_args = server.parse(args, errex=1)
    if not parsed_args.getmod('showhelp'):
        server.main()

if __name__ == '__main__':
    main()
