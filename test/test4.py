class A():
    def a1(self):
        print('a1')

    def a2(self):
        print('a2')

class B(A):
    def a1(self):
        print('b\'s a1')

    def a2(self):
        print('b\'s a2')

    def a3(self):
        print('b\'s a3')

class C(B):
    def a1(self):
        print('c\'s a1')

    def a2(self):
        print('c\'s a2')

    def a3(self):
        print('c\'s a3')

    def a4(self):
        print('c\'s a4')