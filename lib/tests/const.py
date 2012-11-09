# -*- coding: utf-8 -*-
import os
import sys
sys.path.insert(0, 'client')
sys.path.insert(0, '../../client')
sys.path.insert(0, '.')
sys.path.insert(0, '../')
import unittest
import tests._misc as _misc
from entropy.const import const_drop_privileges, const_regain_privileges
from entropy.exceptions import SecurityError

class ConstTest(unittest.TestCase):

    def setUp(self):
        sys.stdout.write("%s called\n" % (self,))
        sys.stdout.flush()

    def tearDown(self):
        """
        tearDown is run after each test
        """
        sys.stdout.write("%s ran\n" % (self,))
        sys.stdout.flush()

    def test_privileges(self):

        self.assertTrue(os.getuid() == 0)
        self.assertTrue(os.getgid() == 0)
        const_drop_privileges()
        self.assertTrue(os.getuid() != 0)
        self.assertTrue(os.getgid() != 0)

        const_regain_privileges()
        self.assertTrue(os.getuid() == 0)
        self.assertTrue(os.getgid() == 0)

        const_drop_privileges()
        self.assertTrue(os.getuid() != 0)
        self.assertTrue(os.getgid() != 0)
        const_drop_privileges()
        self.assertTrue(os.getuid() != 0)
        self.assertTrue(os.getgid() != 0)
        const_regain_privileges()
        self.assertTrue(os.getuid() == 0)
        self.assertTrue(os.getgid() == 0)

if __name__ == '__main__':
    unittest.main()
    entropy.tools.kill_threads()
    raise SystemExit(0)
