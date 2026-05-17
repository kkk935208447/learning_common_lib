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


from random import choice

# # 快排
# def quick_sort(num_list):
#     # 终止条件
#     if len(num_list) <= 1:
#         return num_list
    
#     # 递归
#     povit = choice(num_list)
#     left = []
#     right = []
#     mid = [] 
#     for num in num_list:
#         if num < povit:
#             left.append(num)
#         elif num == povit:
#             mid.append(num)
#         else:
#             right.append(num)

#     return quick_sort(left) + mid + quick_sort(right)

# l1 = [93,3,5,5,6,7,89,3]

# print(quick_sort(l1))

# 快速选择
def quick_select(num_list, k): 

    # 递归 + 剪枝
    pivot = choice(num_list)
    left = []
    right = []
    mid = [] 
    for num in num_list:
        if num < pivot:
            left.append(num)
        elif num == pivot:
            mid.append(num)
        else:
            right.append(num)

    if len(right) >= k:
        return quick_select(right, k)
    # 终止条件
    if len(right) + len(mid) >= k:
        return pivot
    if len(right) + len(mid) < k:
        return quick_select(left, k - len(right) - len(mid))

l2 = [93,3,5,5,6,7,89,89,89,89,3]
print(quick_select(l2, k=1))


# 

