# Pretty-printers for LLVM libc++ 3.7.0
# (Tested with Python 2.7.12 and GDB 7.12)

# Copyright (C) 2008-2018 Free Software Foundation, Inc.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import re
import gdb
import sys

if sys.version_info[0] > 2:
   # Python 3 stuff
   Iterator = object
   # Python 3 folds these into the normal functions.
   imap = map
   izip = zip
   # Also, int subsumes long
   long = int
else:
   # Python 2 stuff
   class Iterator(object):
      """Compatibility mixin for iterators

      Instead of writing next() methods for iterators, write
      __next__() methods and use this mixin to make them work in
      Python 2 as well as Python 3.

      Idea stolen from the "six" documentation:
      <http://pythonhosted.org/six/#six.Iterator>
      """

      def next(self):
         return self.__next__()

   # In Python 2, we still need these from itertools
   from itertools import imap, izip

# Try to use the new-style pretty-printing if available.
_use_gdb_pp = True
try:
   import gdb.printing
except ImportError:
   _use_gdb_pp = False

# Try to install type-printers.
_use_type_printing = False
try:
   import gdb.types
   if hasattr(gdb.types, 'TypePrinter'):
      _use_type_printing = True
except ImportError:
   pass

class StdStringPrinter:
   "Print a std::basic_string of some kind"

   def __init__(self, typename, val):
      self.typename = typename

      # Figure out pointer and size:
      ss = val['__r_']['__first_']['__s']
      __short_mask = 0x1
      if (ss['__size_'] & __short_mask) == 0:
         self.size = (ss['__size_'] >> 1)
         self.ptr = ss['__data_']
      else:
         sl = val['__r_']['__first_']['__l']
         self.size = sl['__size_']
         self.ptr = sl['__data_']

      try:
         if self.size >= 0:
            # Audit plausibility of string by trying to access first and
            #  last character. Failures doing this will much faster than
            #  iterating from a readable address into an unreadable one.
            char_ptr_type = val.type.template_argument(0).pointer()
            first_char_ptr = self.ptr.cast(char_ptr_type)
            first_char = first_char_ptr.dereference()
            last_char_ptr = first_char_ptr + self.size
            last_char = last_char_ptr.dereference()
            # Force read from memory:
            temp_str = '%s, %s' % (first_char, last_char)
            self.display_hint = self._display_hint
      except:
         self.ptr = 0
         self.size = -1

   def to_string(self):
      try:
         if self.size >= 0:
            return self.ptr.string(length=self.size)
      except:
         pass
      return 'invalid'

   def _display_hint(self):
      return 'string'

class PointerPrinter(object):
   "Print a unique_ptr, shared_ptr or weak_ptr"

   def __init__(self, typename, ptr):
      self.ptr = ptr
      self.val = None
      self.visualizer = None
      if self.ptr != 0:
         self.val = self.ptr.dereference()
         # Dereference base type with visualizer, if it exists.
         # Also, inherit iteratability, if that is a word.
         self.visualizer = gdb.default_visualizer(self.val)
         if ((self.visualizer is not None) and
             hasattr(self.visualizer, 'children')):
            self.children = self._children

   def _children(self):
      return self.visualizer.children()

   def to_string(self):
      if self.val is None:
         return 'empty'
      val = self.val
      if self.visualizer is not None:
         val = self.visualizer.to_string()
         if (hasattr(self.visualizer, 'display_hint') and
             self.visualizer.display_hint() == 'string'):
            val = '"%s"' % val
      return '%s => %s' % (self.ptr, val)

   def display_hint(self):
      if (hasattr(self.visualizer, 'display_hint') and
          self.visualizer.display_hint() != 'string'):
         return self.visualizer.display_hint()
      return None

class SharedPointerPrinter(PointerPrinter):
   "Print a shared_ptr or weak_ptr"

   def __init__(self, typename, val):
      super(SharedPointerPrinter, self).__init__(typename, val['__ptr_'])

class UniquePointerPrinter(PointerPrinter):
   "Print a unique_ptr"

   def __init__(self, typename, val):
      super(UniquePointerPrinter, self).__init__(typename, val['__ptr_']['__first_'])

class StdPairPrinter:
   "Print a std::pair"

   def __init__(self, typename, val):
      self.typename = typename
      self.val = val

   def children(self):
      return [('[0] = first ', self.val['first']),
              ('[1] = second', self.val['second'])]

   def to_string(self):
      return 'pair'

class StdTuplePrinter:
   "Print a std::tuple"

   class _iterator(Iterator):
      def __init__(self, head):
         self.head = head['base_']
         self.fields = self.head.type.fields()
         self.count = 0

      def __iter__(self):
         return self

      def __next__(self):
         if self.count >= len(self.fields):
            raise StopIteration
         field = self.head.cast(self.fields[self.count].type)['value']
         self.count += 1
         return ('[%d]' % (self.count - 1), field)

   def __init__(self, typename, val):
      self.typename = typename
      self.val = val

   def children(self):
      return self._iterator(self.val)

   def to_string(self):
      if len(self.val.type.fields()) == 0:
         return 'empty'
      return 'tuple'

class StdListPrinter:
   "Print a std::list"

   class _iterator(Iterator):
      def __init__(self, head, num_nodes):
         self.head = head.address
         self.base = head['__next_']
         self.num_nodes = num_nodes
         self.nodetype = self.base.type
         self.count = 0

      def __iter__(self):
         return self

      def __next__(self):
         if ((self.base == self.head) or
             (self.count == self.num_nodes)):
            raise StopIteration
         elt = self.base.cast(self.nodetype).dereference()
         self.base = elt['__next_']
         count = self.count
         self.count = self.count + 1
         return ('[%d]' % count, elt['__value_'])

   def __init__(self, typename, val):
      self.typename = typename
      self.val = val
      self.size = val['__size_alloc_']['__first_']
      try:
         iterator = self._children()           # Get size by counting iterations and ...
         if self.size != len(list(iterator)):  #  compare with self.size
            self.size = -1                     #  Invalidate if no match
         elif self.size > 0:
            self.children = self._children     # Only provide children method if we have some
      except:
         self.size = -1

   def _children(self):
      return self._iterator(self.val['__end_'], self.size)

   def to_string(self):
      try:
         if self.size == 0:
            return 'empty'
         elif self.size > 0:
            return '%s (length=%d)' % (self.typename, int(self.size))
      except:
         pass
      return 'invalid'

class StdListIteratorPrinter:
   "Print std::list::iterator or std::forward_list::iterator"

   def __init__(self, typename, val):
      self.ptr = val['__ptr_']
      self.typename = typename

   def to_string(self):
      if self.ptr == 0:
         return 'invalid'
      return self.ptr['__value_']

class StdForwardListPrinter:
   "Print a std::forward_list"

   class _iterator(Iterator):
      def __init__(self, head):
         self.node = head
         self.count = 0

      def __iter__(self):
         return self

      def __next__(self):
         if self.node == 0:
            raise StopIteration

         result = ('[%d]' % self.count, self.node['__value_'])
         self.count += 1
         self.node = self.node['__next_']
         return result

   def __init__(self, typename, val):
      self.val = val
      self.typename = typename
      self.head = val['__before_begin_']['__first_']['__next_']
      try:
         iterator = self._children() # Get size by counting iterations
         self.size = len(list(iterator))
      except:
         self.size = -1
      if self.size > 0:
            self.children = self._children     # Only provide children method if we have some

   def _children(self):
      return self._iterator(self.head)

   def to_string(self):
      try:
         if self.size == 0:
            return 'empty'
         elif self.size > 0:
            return '%s (length=%d)' % (self.typename, int(self.size))
      except:
         pass
      return 'invalid'

class StdArrayPrinter:
   "Print a std::array"

   class _iterator(Iterator):
      def __init__(self, val, size):
         self.val = val
         self.size = size
         self.count = 0

      def __iter__(self):
         return self

      def __next__(self):
         if self.count >= self.size:
            raise StopIteration

         elem = self.val[self.count]
         return_tuple = ('[%d]' % self.count, elem)
         self.count += 1
         return return_tuple

   def __init__(self, typename, val):
      self.typename = typename
      self.val = val['__elems_']
      self.size = val.type.template_argument(1)

   def children(self):
      return self._iterator(self.val,self.size)

   def to_string(self):
      return '(length=%d)' % self.size

class StdVectorPrinter:
   "Print a std::vector"

   class _iterator(Iterator):
      def __init__(self, start, finish_or_size, bits_per_word, bitvec):
         self.bitvec = bitvec
         if bitvec:
            self.item = start
            self.so = 0
            self.size = finish_or_size
            self.bits_per_word = bits_per_word
         else:
            self.item = start
            self.finish = finish_or_size
         self.count = 0

      def __iter__(self):
         return self

      def __next__(self):
         count = self.count
         self.count = self.count + 1
         if self.bitvec:
            if count == self.size:
               raise StopIteration
            elt = self.item.dereference()
            if elt & (1 << self.so):
               obit = True
            else:
               obit = False
            self.so = self.so + 1
            if self.so >= self.bits_per_word:
               self.item = self.item + 1
               self.so = 0
            return ('[%d]' % count, obit)
         else:
            if self.item == self.finish:
               raise StopIteration
            elt = self.item.dereference()
            self.item = self.item + 1
            return ('[%d]' % count, elt)

   def __init__(self, typename, val):
      self.typename = typename
      self.val = val
      self.is_bool = 0
      for f in val.type.fields():
         if f.name == '__bits_per_word':
            self.is_bool = 1
            if self.val['__bits_per_word'].is_optimized_out:
               self.bits_per_word = 64 # Correct for the moment
            else:
               self.bits_per_word = self.val['__bits_per_word']
      if self.is_bool:
         self.size = self.val['__size_']
         self.capacity = self.val['__cap_alloc_']['__first_'] * self.bits_per_word
      else:
         self.size = self.val['__end_'] - self.val['__begin_']
         self.capacity = self.val['__end_cap_']['__first_'] - self.val['__begin_']

      if self.size > self.capacity:
         self.size = -1 # Implausible

      if self.size > 0:
         # Audit plausibility of string by trying to access first and
         #  last character. Failures doing this will much faster than
         #  iterating from a readable address into an unreadable one.
         try:
            front_ptr = self.val['__begin_']
            if self.is_bool:
               back_ptr = front_ptr + ((self.size - 1)/self.bits_per_word)
            else:
               back_ptr = self.val['__end_'] - 1
            # Force read from memory:
            temp_str = '%s, %s' % (front_ptr.dereference(), back_ptr.dereference())
            # If read didn't throw exception, we are comfortable walking this
            #  vector
            self.children = self._children
         except:
            self.size = -1

   def _children(self):
      if self.is_bool:
         return self._iterator(self.val['__begin_'],
                               self.val['__size_'],
                               self.bits_per_word,
                               self.is_bool)
      else:
         return self._iterator(self.val['__begin_'],
                               self.val['__end_'],
                               0,
                               self.is_bool)

   def to_string(self):
      try:
         if self.size == 0:
            return 'empty'
         elif self.size > 0:
            start = self.val['__begin_']
            if self.is_bool:
               capacity = self.val['__cap_alloc_']['__first_'] * self.bits_per_word
               if self.size == 0:
                  return 'empty %s<bool> (capacity=%d)' % (self.typename, int(capacity))
               else:
                  return '%s<bool> (length=%d, capacity=%d)' % (self.typename, int(self.size), int(capacity))
            else:
               finish = self.val['__end_']
               end = self.val['__end_cap_']['__first_']
               capacity = end - start
               if self.size == 0:
                  return 'empty %s (capacity=%d)' % (self.typename, int(capacity))
               else:
                  return '%s (length=%d, capacity=%d)' % (self.typename, int(self.size), int(capacity))
      except:
         pass
      return 'invalid'

class StdVectorIteratorPrinter:
   "Print std::vector::iterator"

   def __init__(self, typename, val):
      self.val = val

   def to_string(self):
      try:
         return ('%s' % (self.val['__i'].dereference()))
      except:
         return 'invalid'

class StdVectorBoolIteratorPrinter:
   "Print std::vector<bool>::iterator"

   def __init__(self, typename, val):
      self.segment = val['__seg_'].dereference()
      self.ctz = val['__ctz_']

   def to_string(self):
      try:
         if self.segment & (1 << self.ctz):
            return True
         else:
            return False
      except:
         return 'invalid'

class StdSplitBufferPrinter:

   class _iterator(Iterator):
      def __init__(self, begin, end):
         self.ptr   = begin
         self.end   = end
         self.count = 0

      def __iter__(self):
         return self

      def __next__(self):
         if self.ptr >= self.end:
            raise StopIteration
         return_tuple = ('[%d]' % int(self.count), self.ptr.dereference())
         self.count += 1
         self.ptr += 1
         return return_tuple

   def __init__(self, val):
      self.begin     = val['__begin_']
      self.end       = val['__end_']
      self.end_cap   = val['__end_cap_']['__first_']
      self.size     = self.end     - self.begin
      self.capacity = self.end_cap - self.begin
      if self.capacity < self.size:
         self.size     = -1
         self.capacity = -1
      try:
         if self.size > 0:
            iterator = self._children()           # Get size by counting iterations and ...
            if self.size != len(list(iterator)):  #  compare with self.size
               self.size     = -1                 #  Invalidate if no match
               self.capacity = -1
            else:
               self.children = self._children # Only provide children method if we have some
      except:
         self.size = -1
         self.capacity = -1

   def size(self):
      return self.size

   def capacity(self):
      return self.capacity

   def to_string(self):
      try:
         if self.size == 0:
            return 'empty'
         elif self.size > 0:
            return '(length=%d, capacity=%d)' % (self.size, self.capacity)
      except:
         pass
      return 'invalid'

   def _children(self):
      return self._iterator(self.begin, self.end)

class StdDequePrinter:
   "Print a std::deque"

   class _iterator(Iterator):
      def __init__(self, size, block_size, start, map_begin, map_end):
         self.count = 0
         self.size = size
         self.block_size = block_size
         self.start = start
         self.map_begin = map_begin
         self.map_end = map_end

      def __iter__(self):
         return self

      def __next__(self):
         if self.count >= self.size:
            raise StopIteration
         if self.start > self.block_size:
            raise StopIteration

         # Code snippets from:
         #    deque<_Tp, _Allocator>::operator[](size_type __i):
         # size_type __p = __base::__start_ + __i;
         idx = self.start + self.count
         # return *(*(__base::__map_.begin() + __p / __base::__block_size) + __p % __base::__block_size);
         block_ptr = self.map_begin + (idx / self.block_size)
         if block_ptr >= self.map_end:
            raise StopIteration
         idx %= self.block_size
         data_ptr = block_ptr.dereference() + idx

         return_tuple = ('[%d]' % int(self.count), data_ptr.dereference())
         self.count += 1
         return return_tuple

   def __init__(self, typename, val):
      self.typename   = typename
      self.block_size = val['__block_size']
      self.blocks     = StdSplitBufferPrinter(val['__map_'])
      self.start      = val['__start_']
      self.size       = val['__size_']['__first_']
      self.capacity   = self.blocks.capacity * self.block_size
      #try:
      if ((self.size > 0) and
          (self.start < self.block_size) and
          (hasattr(self.blocks, 'children')) and
          (self.size <= (self.blocks.size * self.block_size))):
         # Attempt to dereference each of the block pointers as a quick
         #  litmus test of whether this data structure is valid
         for (idx, ptr) in self.blocks.children():
            test_str = '%s' % ptr.dereference()
         iterator = self._children()           # Get size by counting iterations and ...
         if self.size != len(list(iterator)):  #  compare with self.size
            self.size = -1                     #  Invalidate if no match
         else:
            self.children = self._children     # Only provide children method if we have some
      else:
         self.size = -1
      #except:
      #   self.size     = -1

   def to_string(self):
      try:
         if self.size == 0:
            return 'empty'
         elif self.size > 0:
            return '%s (length=%d, capacity=%d)' % (self.typename, self.size, self.capacity)
      except:
         pass
      return 'invalid'

   def _children(self):
      return self._iterator(self.size, self.block_size, self.start,
                            self.blocks.begin, self.blocks.end)

class StdDequeIteratorPrinter:
   "Print std::deque::iterator"

   def __init__(self, typename, val):
      self.val = val

   def to_string(self):
      try:
         return '%s' % self.val['__ptr_'].dereference()
      except:
         return 'invalid'

class StdStackOrQueuePrinter:
   "Print a std::stack or std::queue"

   def __init__(self, typename, val):
      self.typename = typename
      self.visualizer = gdb.default_visualizer(val['c'])
      if hasattr(self.visualizer, 'children'):
         self.children = self._children

   def _children(self):
      return self.visualizer.children()

   def to_string(self):
      return '%s = %s' % (self.typename, self.visualizer.to_string())

   def display_hint(self):
      if hasattr(self.visualizer, 'display_hint'):
         return self.visualizer.display_hint()
      return None

class StdBitsetPrinter:
   "Print a std::bitset"

   def __init__(self, typename, val):
      self.typename = typename
      self.val = val
      self.bit_count = val.type.template_argument(0)

   def to_string(self):
      return '%s (length=%d)' % (self.typename, self.bit_count)

   def children(self):
      words = self.val['__first_']
      words_count = self.val['__n_words']
      if self.val['__bits_per_word'].is_optimized_out:
         bits_per_word = 64 # Correct for the moment
      else:
         bits_per_word = self.val['__bits_per_word']
      word_index = 0
      result = []

      while word_index < words_count:
         bit_index = 0
         if words_count == 1:
            word = words
         else:
            word = words[word_index]
         while word != 0:
            if (word & 0x1) != 0:
               result.append(('[%d]' % (word_index * bits_per_word + bit_index), 1))
            word >>= 1
            bit_index += 1
         word_index += 1

      return result

class StdRbtreePrinter(object):
   class _iterator(Iterator):
      def __init__(self, rbtree):
         self.node = rbtree['__begin_node_']
         self.size = rbtree['__pair3_']['__first_']
         if self.size < 0:
            self.size = 0
         self.node_pointer_type = gdb.lookup_type(rbtree.type.strip_typedefs().name + '::__node_pointer')
         self.count = 0

      def __iter__(self):
         return self

      def __len__(self):
         return int(self.size)

      def __next__(self):
         if self.count >= self.size:
            raise StopIteration

         node = self.node.cast(self.node_pointer_type)
         result = node
         # Compute the next node.
         try:
            if node.dereference()['__right_']:
               node = node.dereference()['__right_']
               while node.dereference()['__left_']:
                  node = node.dereference()['__left_']
            else:
               parent_node = node.dereference()['__parent_']
               while node != parent_node.dereference()['__left_']:
                  node = parent_node
                  parent_node = parent_node.dereference()['__parent_']
               node = parent_node

            return_tuple = (('[%d]' % self.count), result.dereference()['__value_'])

         except:
            raise StopIteration

         self.node = node
         self.count += 1
         return return_tuple

   def __init__(self, typename, val):
      self.typename = typename
      self.val = val
      try:
         iterator = self._children()
         self.size = len(list(iterator)) # Get size by counting iterations and ...
         if self.size != len(iterator):  #  compare with size from __len__ method
            self.size = -1               #  Invalidate if no match
         elif self.size > 0:
            self.children = self._children  # Only provide children method if we have some
      except:
         self.size = -1

   def to_string(self):
      try:
         if self.size == 0:
            return 'empty'
         elif self.size > 0:
            return '%s (count=%d)' % (self.typename, int(self.size))
      except:
         pass
      return 'invalid'

   def _children(self):
      return self._iterator(self.val)

class StdRbtreeIteratorPrinter:
   "Print std::set::iterator or std::multiset::iterator"

   def __init__(self, typename, val):
      self.val = val

   def to_string(self):
      try:
         return '%s' % self.val['__ptr_']['__value_']
      except:
         return 'invalid'

class StdSetPrinter(StdRbtreePrinter):
   "Print a std::set or std::multiset"

   def __init__(self, typename, val):
      super(StdSetPrinter, self).__init__(typename, val['__tree_'])

class StdMapPrinter(StdRbtreePrinter):
   "Print a std::map or std::multimap"

   # Turn an RbtreeIterator into a pretty-print iterator.
   class _iterator(StdRbtreePrinter._iterator):
      def __init__(self, val):
         super(StdMapPrinter._iterator, self).__init__(val)

      def __next__(self):
         try:
            (idx_str, item) = super(StdMapPrinter._iterator, self).__next__()
            idx_str += ' %s' % str(item['__cc']['first'])
            return (idx_str, item['__cc']['second'])
         except:
            raise StopIteration

   def __init__(self, typename, val):
      super(StdMapPrinter, self).__init__(typename, val['__tree_'])

   def _children(self):
      return self._iterator(self.val)

class StdMapIteratorPrinter:
   "Print std::map::iterator"

   def __init__(self, typename, val):
      self.val = val

   def to_string(self):
      try:
         return '[%s] %s' % (self.val['__i_']['__ptr_']['__value_']['__cc']['first'],
                             self.val['__i_']['__ptr_']['__value_']['__cc']['second'])
      except:
         return 'invalid'

class HashTablePrinter(object):
   class _iterator(Iterator):
      def __init__(self, hashtable):
         self.node = hashtable['__p1_']['__first_']['__next_']
         self.size = hashtable['__p2_']['__first_']
         if self.size < 0:
            self.size = 0
         self.count = 0

      def __iter__(self):
         return self

      def __len__(self):
         return self.size

      def __next__(self):
         if self.count >= self.size:
            raise StopIteration
         if self.node == 0:
            raise StopIteration

         try:
            node = self.node.dereference()
            self.node = node['__next_']
            value = node['__value_']
            throw_exception_for_invalid_memory = '%s' % value
            return_tuple = (('[%d]' % self.count), value)
         except:
            raise StopIteration

         self.count += 1
         return return_tuple

   def __init__(self, typename, val):
      self.typename = typename
      self.val = val
      try:
         iterator = self._children()
         self.size = len(list(iterator)) # Get size by counting iterations and ...
         if self.size != len(iterator):  #  compare with size from __len__ method
            self.size = -1               #  Invalidate if no match
         elif self.size > 0:
            self.children = self._children  # Only provide children method if we have some
      except:
         self.size = -1

   def to_string(self):
      try:
         if self.size == 0:
            return 'empty'
         elif self.size > 0:
            return '%s (count=%d)' % (self.typename, int(self.size))
      except:
         pass
      return 'invalid'

   def _children(self):
      return self._iterator(self.val)


class StdHashtableIteratorPrinter:
   "Print std::unordered_set::iterator or std::unordered_multiset::iterator"

   def __init__(self, typename, val):
      self.val = val

   def to_string(self):
      try:
         return '%s' % self.val['__node_']['__value_']
      except:
         return 'invalid'

class StdUnorderedMapIteratorPrinter:
   "Print std::unordered_map::iterator"

   def __init__(self, typename, val):
      self.pair = val['__i_']['__node_']['__value_']['__cc']

   def to_string(self):
      try:
         return '[%s] %s' % (self.pair['first'], self.pair['second'])
      except:
         return 'invalid'

class UnorderedSetPrinter(HashTablePrinter):
   "Print a std::unordered_set or std::unordered_multiset"

   def __init__(self, typename, val):
      super(UnorderedSetPrinter, self).__init__(typename, val['__table_'])

class UnorderedMapPrinter(HashTablePrinter):
   "Print a std::unordered_map"

   # Turn an HashTablePrinter into a pretty-print iterator.
   class _iterator(HashTablePrinter._iterator):
      def __init__(self, val):
         super(UnorderedMapPrinter._iterator, self).__init__(val)

      def __next__(self):
         try:
            (idx_str, item) = super(UnorderedMapPrinter._iterator, self).__next__()
            idx_str += ' %s' % str(item['__cc']['first'])
            return (idx_str, item['__cc']['second'])
         except:
            raise StopIteration

   def __init__(self, typename, val):
      super(UnorderedMapPrinter, self).__init__(typename, val['__table_'])

   def _children(self):
      return self._iterator(self.val)

# A "regular expression" printer which conforms to the
# "SubPrettyPrinter" protocol from gdb.printing.
class RxPrinter(object):
   def __init__(self, name, function):
      super(RxPrinter, self).__init__()
      self.name = name
      self.function = function
      self.enabled = True

   def invoke(self, value):
      if not self.enabled:
         return None
      return self.function(self.name, value)

# A pretty-printer that conforms to the "PrettyPrinter" protocol from
# gdb.printing.  It can also be used directly as an old-style printer.
class Printer(object):
   def __init__(self, name):
      super(Printer, self).__init__()
      self.name = name
      self.subprinters = []
      self.lookup = {}
      self.enabled = True
      self.compiled_rx = re.compile('^([a-zA-Z0-9_:]+)<.*>$')

   def add(self, name, function):
      # A small sanity check.
      # FIXME
      if not self.compiled_rx.match(name + '<>'):
         raise ValueError('libstdc++ programming error: "%s" does not match' % name)
      printer = RxPrinter(name, function)
      self.subprinters.append(printer)
      self.lookup[name] = printer

   # Add a name using _GLIBCXX_BEGIN_NAMESPACE_VERSION.
   def add_version(self, base, name, function):
      self.add(base + name, function)
      self.add(base + '__1::' + name, function)

   # Add a name using _GLIBCXX_BEGIN_NAMESPACE_CONTAINER.
   def add_container(self, base, name, function):
      self.add_version(base, name, function)
      self.add_version(base + '__1::', name, function)

   @staticmethod
   def get_basic_type(type):
      # If it points to a reference, get the reference.
      if type.code == gdb.TYPE_CODE_REF:
         type = type.target()

      # Get the unqualified type, stripped of typedefs.
      type = type.unqualified().strip_typedefs()

      return type.tag

   def __call__(self, val):
      typename = self.get_basic_type(val.type)
      if not typename:
         return None

      # All the types we match are template types, so we can use a
      # dictionary.
      match = self.compiled_rx.match(typename)
      if not match:
         return None

      basename = match.group(1)
      if basename in self.lookup:
         return self.lookup[basename].invoke(val)

      # Cannot find a pretty printer.  Return None.
      return None

libcxx_printer = None

class FilteringTypePrinter(object):
   def __init__(self, match, name):
      self.match = match
      self.name = name
      self.enabled = True

   class _recognizer(object):
      def __init__(self, match, name):
         self.match = match
         self.name = name
         self.type_obj = None

      def recognize(self, type_obj):
         if type_obj.tag is None:
            return None

         if self.type_obj is None:
            if not self.match in type_obj.tag:
               # Filter didn't match.
               return None
            try:
               self.type_obj = gdb.lookup_type(self.name).strip_typedefs()
            except:
               pass
         if self.type_obj == type_obj:
            return self.name
         return None

   def instantiate(self):
      return self._recognizer(self.match, self.name)

def add_one_type_printer(obj, match, name):
   printer = FilteringTypePrinter(match, 'std::' + name)
   gdb.types.register_type_printer(obj, printer)

def register_type_printers(obj):
   global _use_type_printing

   if not _use_type_printing:
      return

   for pfx in ('', 'w'):
      add_one_type_printer(obj, 'basic_string', pfx + 'string')
      add_one_type_printer(obj, 'basic_ios', pfx + 'ios')
      add_one_type_printer(obj, 'basic_streambuf', pfx + 'streambuf')
      add_one_type_printer(obj, 'basic_istream', pfx + 'istream')
      add_one_type_printer(obj, 'basic_ostream', pfx + 'ostream')
      add_one_type_printer(obj, 'basic_iostream', pfx + 'iostream')
      add_one_type_printer(obj, 'basic_stringbuf', pfx + 'stringbuf')
      add_one_type_printer(obj, 'basic_istringstream',
                           pfx + 'istringstream')
      add_one_type_printer(obj, 'basic_ostringstream',
                           pfx + 'ostringstream')
      add_one_type_printer(obj, 'basic_stringstream',
                           pfx + 'stringstream')
      add_one_type_printer(obj, 'basic_filebuf', pfx + 'filebuf')
      add_one_type_printer(obj, 'basic_ifstream', pfx + 'ifstream')
      add_one_type_printer(obj, 'basic_ofstream', pfx + 'ofstream')
      add_one_type_printer(obj, 'basic_fstream', pfx + 'fstream')
      add_one_type_printer(obj, 'basic_regex', pfx + 'regex')
      add_one_type_printer(obj, 'sub_match', pfx + 'csub_match')
      add_one_type_printer(obj, 'sub_match', pfx + 'ssub_match')
      add_one_type_printer(obj, 'match_results', pfx + 'cmatch')
      add_one_type_printer(obj, 'match_results', pfx + 'smatch')
      add_one_type_printer(obj, 'regex_iterator', pfx + 'cregex_iterator')
      add_one_type_printer(obj, 'regex_iterator', pfx + 'sregex_iterator')
      add_one_type_printer(obj, 'regex_token_iterator',
                           pfx + 'cregex_token_iterator')
      add_one_type_printer(obj, 'regex_token_iterator',
                           pfx + 'sregex_token_iterator')

   # Note that we can't have a printer for std::wstreampos, because
   # it shares the same underlying type as std::streampos.
   add_one_type_printer(obj, 'fpos', 'streampos')
   add_one_type_printer(obj, 'basic_string', 'u16string')
   add_one_type_printer(obj, 'basic_string', 'u32string')

   for dur in ('nanoseconds', 'microseconds', 'milliseconds',
               'seconds', 'minutes', 'hours'):
      add_one_type_printer(obj, 'duration', dur)

   add_one_type_printer(obj, 'linear_congruential_engine', 'minstd_rand0')
   add_one_type_printer(obj, 'linear_congruential_engine', 'minstd_rand')
   add_one_type_printer(obj, 'mersenne_twister_engine', 'mt19937')
   add_one_type_printer(obj, 'mersenne_twister_engine', 'mt19937_64')
   add_one_type_printer(obj, 'subtract_with_carry_engine', 'ranlux24_base')
   add_one_type_printer(obj, 'subtract_with_carry_engine', 'ranlux48_base')
   add_one_type_printer(obj, 'discard_block_engine', 'ranlux24')
   add_one_type_printer(obj, 'discard_block_engine', 'ranlux48')
   add_one_type_printer(obj, 'shuffle_order_engine', 'knuth_b')

def register_libcxx_printers(obj):
   "Register libc++ pretty-printers with objfile Obj."

   global _use_gdb_pp
   global libcxx_printer

   if _use_gdb_pp:
      gdb.printing.register_pretty_printer(obj, libcxx_printer)
   else:
      if obj is None:
         obj = gdb
      obj.pretty_printers.append(libcxx_printer)

   register_type_printers(obj)

def build_libcxx_dictionary():
   global libcxx_printer

   libcxx_printer = Printer("libc++-v1")

   # For _GLIBCXX_BEGIN_NAMESPACE_VERSION.
   vers = '(__1::)?'
   # For _GLIBCXX_BEGIN_NAMESPACE_CONTAINER.
   container = '(__cxx2011::' + vers + ')?'

   # libstdc++ objects requiring pretty-printing.
   # In order from:
   # http://gcc.gnu.org/onlinedocs/libstdc++/latest-doxygen/a01847.html
   libcxx_printer.add_version('std::', 'basic_string', StdStringPrinter)
   libcxx_printer.add_container('std::', 'bitset', StdBitsetPrinter)
   libcxx_printer.add_container('std::', 'deque', StdDequePrinter)
   libcxx_printer.add_container('std::', 'list', StdListPrinter)
   libcxx_printer.add_container('std::', 'map', StdMapPrinter)
   libcxx_printer.add_container('std::', 'multimap', StdMapPrinter)
   libcxx_printer.add_container('std::', 'multiset', StdSetPrinter)
   libcxx_printer.add_version('std::', 'priority_queue',
                              StdStackOrQueuePrinter)
   libcxx_printer.add_version('std::', 'queue', StdStackOrQueuePrinter)
   libcxx_printer.add_version('std::', 'tuple', StdTuplePrinter)
   libcxx_printer.add_version('std::', 'pair', StdPairPrinter)
   libcxx_printer.add_container('std::', 'set', StdSetPrinter)
   libcxx_printer.add_version('std::', 'stack', StdStackOrQueuePrinter)
   libcxx_printer.add_version('std::', 'unique_ptr', UniquePointerPrinter)
   libcxx_printer.add_container('std::', 'array', StdArrayPrinter)
   libcxx_printer.add_container('std::', 'vector', StdVectorPrinter)

   # Printer registrations for classes compiled with -D_GLIBCXX_DEBUG.
   libcxx_printer.add('std::__debug::bitset', StdBitsetPrinter)
   libcxx_printer.add('std::__debug::deque', StdDequePrinter)
   libcxx_printer.add('std::__debug::list', StdListPrinter)
   libcxx_printer.add('std::__debug::map', StdMapPrinter)
   libcxx_printer.add('std::__debug::multimap', StdMapPrinter)
   libcxx_printer.add('std::__debug::multiset', StdSetPrinter)
   libcxx_printer.add('std::__debug::priority_queue', StdStackOrQueuePrinter)
   libcxx_printer.add('std::__debug::queue', StdStackOrQueuePrinter)
   libcxx_printer.add('std::__debug::set', StdSetPrinter)
   libcxx_printer.add('std::__debug::stack', StdStackOrQueuePrinter)
   libcxx_printer.add('std::__debug::unique_ptr', UniquePointerPrinter)
   libcxx_printer.add('std::__debug::array', StdArrayPrinter)
   libcxx_printer.add('std::__debug::vector', StdVectorPrinter)

   # For array - the default GDB pretty-printer seems reasonable.
   libcxx_printer.add_version('std::', 'shared_ptr', SharedPointerPrinter)
   libcxx_printer.add_version('std::', 'weak_ptr', SharedPointerPrinter)
   libcxx_printer.add_container('std::', 'unordered_map', UnorderedMapPrinter)
   libcxx_printer.add_container('std::', 'unordered_set', UnorderedSetPrinter)
   libcxx_printer.add_container('std::', 'unordered_multimap',
                                UnorderedMapPrinter)
   libcxx_printer.add_container('std::', 'unordered_multiset',
                                UnorderedSetPrinter)
   libcxx_printer.add_container('std::', 'forward_list', StdForwardListPrinter)

   libcxx_printer.add_version('std::', 'shared_ptr', SharedPointerPrinter)
   libcxx_printer.add_version('std::', 'weak_ptr', SharedPointerPrinter)
   libcxx_printer.add_version('std::', 'unordered_map', UnorderedMapPrinter)
   libcxx_printer.add_version('std::', 'unordered_set', UnorderedSetPrinter)
   libcxx_printer.add_version('std::', 'unordered_multimap',
                              UnorderedMapPrinter)
   libcxx_printer.add_version('std::', 'unordered_multiset',
                              UnorderedSetPrinter)

   # These are the C++0x printer registrations for -D_GLIBCXX_DEBUG cases.
   libcxx_printer.add('std::__debug::unordered_map', UnorderedMapPrinter)
   libcxx_printer.add('std::__debug::unordered_set', UnorderedSetPrinter)
   libcxx_printer.add('std::__debug::unordered_multimap', UnorderedMapPrinter)
   libcxx_printer.add('std::__debug::unordered_multiset', UnorderedSetPrinter)
   libcxx_printer.add('std::__debug::forward_list', StdForwardListPrinter)

   libcxx_printer.add_container('std::', '__list_iterator',
                                StdListIteratorPrinter)
   libcxx_printer.add_container('std::', '__list_const_iterator',
                                StdListIteratorPrinter)
   libcxx_printer.add_container('std::', '__forward_list_iterator',
                                StdListIteratorPrinter)
   libcxx_printer.add_container('std::', '__forward_list_const_iterator',
                                StdListIteratorPrinter)
   libcxx_printer.add_version('std::', '__tree_iterator',
                              StdRbtreeIteratorPrinter)
   libcxx_printer.add_version('std::', '__tree_const_iterator',
                              StdRbtreeIteratorPrinter)
   libcxx_printer.add_version('std::', '__hash_iterator',
                              StdHashtableIteratorPrinter)
   libcxx_printer.add_version('std::', '__hash_const_iterator',
                              StdHashtableIteratorPrinter)
   libcxx_printer.add_version('std::', '__hash_map_iterator',
                              StdUnorderedMapIteratorPrinter)
   libcxx_printer.add_version('std::', '__hash_map_const_iterator',
                              StdUnorderedMapIteratorPrinter)
   libcxx_printer.add_version('std::', '__map_iterator',
                              StdMapIteratorPrinter)
   libcxx_printer.add_version('std::', '__map_const_iterator',
                              StdMapIteratorPrinter)
   libcxx_printer.add_container('std::', '__deque_iterator',
                                StdDequeIteratorPrinter)
   libcxx_printer.add_version('std::', '__wrap_iter',
                              StdVectorIteratorPrinter)
   libcxx_printer.add_version('std::', '__bit_iterator',
                              StdVectorBoolIteratorPrinter)

   # Debug (compiled with -D_GLIBCXX_DEBUG) printer
   # registrations.  The Rb_tree debug iterator when unwrapped
   # from the encapsulating __gnu_debug::_Safe_iterator does not
   # have the __norm namespace. Just use the existing printer
   # registration for that.
   libcxx_printer.add('std::__norm::__list_iterator',
                      StdListIteratorPrinter)
   libcxx_printer.add('std::__norm::__list_const_iterator',
                      StdListIteratorPrinter)
   libcxx_printer.add('std::__norm::__forward_list_iterator',
                      StdListIteratorPrinter)
   libcxx_printer.add('std::__norm::__forward_list_const_iterator',
                      StdListIteratorPrinter)
   libcxx_printer.add('std::__norm::__deque_iterator',
                      StdDequeIteratorPrinter)

build_libcxx_dictionary()
