import random

class SudokuGenerator:
    def __init__(self):
        self.board = [[0 for _ in range(9)] for _ in range(9)]
    
    def is_valid(self, row, col, num):
        for x in range(9):
            if self.board[row][x] == num:
                return False
        for x in range(9):
            if self.board[x][col] == num:
                return False
        start_row = row - row % 3
        start_col = col - col % 3
        for i in range(3):
            for j in range(3):
                if self.board[i + start_row][j + start_col] == num:
                    return False
        return True

    def solve_board(self):
        for row in range(9):
            for col in range(9):
                if self.board[row][col] == 0:
                    numbers = list(range(1, 10))
                    random.shuffle(numbers)
                    for num in numbers:
                        if self.is_valid(row, col, num):
                            self.board[row][col] = num
                            if self.solve_board():
                                return True
                            self.board[row][col] = 0
                    return False
        return True

    def generate_full_board(self):
        self.board = [[0 for _ in range(9)] for _ in range(9)]
        self.solve_board()
        return self.board

    def remove_numbers(self, difficulty):
        cells_to_remove = {'easy': 35, 'medium': 45, 'hard': 55, 'expert': 65}.get(difficulty, 45)
        puzzle = [row[:] for row in self.board]
        cells = [(i, j) for i in range(9) for j in range(9)]
        random.shuffle(cells)
        for i, j in cells[:cells_to_remove]:
            puzzle[i][j] = 0
        return puzzle

    def generate_puzzle(self, difficulty='medium'):
        self.generate_full_board()
        solution = [row[:] for row in self.board]
        puzzle = self.remove_numbers(difficulty)
        return puzzle, solution

    def get_hint(self, puzzle, solution):
        """إرجاع خلية فارغة مع قيمتها الصحيحة للتلميح"""
        empty_cells = [(i, j) for i in range(9) for j in range(9) if puzzle[i][j] == 0]
        if empty_cells:
            i, j = random.choice(empty_cells)
            return {'row': i, 'col': j, 'value': solution[i][j]}
        return None

    @staticmethod
    def check_solution(board):
        for row in range(9):
            for col in range(9):
                if board[row][col] == 0:
                    return False
        for row in range(9):
            if len(set(board[row])) != 9:
                return False
        for col in range(9):
            column = [board[row][col] for row in range(9)]
            if len(set(column)) != 9:
                return False
        for box in range(9):
            start_row = (box // 3) * 3
            start_col = (box % 3) * 3
            box_nums = [board[start_row + i][start_col + j] for i in range(3) for j in range(3)]
            if len(set(box_nums)) != 9:
                return False
        return True
