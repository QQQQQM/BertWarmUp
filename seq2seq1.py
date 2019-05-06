from __future__ import unicode_literals,print_function,division
from io import open
import unicodedata
import string
import re
import random



import torch
import torch.nn as nn
from torch.autograd import Variable
from torch import optim
import torch.nn.functional as F


sos_token = 0
eos_token = 1

class Lang:
    def __init__(self,name):
        self.name = name
        self.word2index = {}
        self.index2word = {0:"sos" ,1:"eos"}
        self.word2count = {}
        self.n_words = 2

    def addSentence(self,sentence):
        for word in sentence.split(' '):
            self.addWord(word)

    def addWord(self,word):
        if word not in self.word2index:
            self.word2index[word] = self.n_words
            self.word2count[word] = 1
            self.index2word[self.n_words] = word
            self.n_words +=1
        else:
            self.word2count[word] +=1

def unicodeToAscii(s):
    return ''.join(
        c for c in unicodedata.normalize('NFD',s)
        if unicodedata.category(c) != 'Mn'
    )

def normalizeString(s):
    s = unicodeToAscii(s.lower().strip())
    s = re.sub(r"([.!?])",r" \1",s)
    s = re.sub(r"[^a-zA-Z.!?]+",r" ",s)
    return s

def readLangs(lang1, lang2, reverse=False):
    print("Reading lines...")

    lines = open('nlpdata/data/%s-%s.txt' % (lang1, lang2), encoding='utf-8').\
        read().strip().split('\n')

    pairs = [[normalizeString(s) for s in l.split('\t')] for l in lines]

    if reverse:
        pairs = [list(reversed(p)) for p in pairs]
        input_lang = Lang(lang2)
        output_lang = Lang(lang1)
    else:
        input_lang = Lang(lang1)
        output_lang = Lang(lang2)

    return input_lang, output_lang, pairs

max_length = 10

eng_prefixes = (
    "i am", "i m",
    "he is", "he s",
    "she is", "she s",
    "you are", "we re"
    "we are", "we re",
    "they are", "they re"
)

def filterPair(p):
    return len(p[0].split(' ')) < max_length and \
        len(p[1].split(' ')) < max_length and \
        p[1].startswith(eng_prefixes)

def filterPairs(pairs):
    return[pair for pair in pairs if filterPair(pair)]

def prepareData(lang1, lang2, reverse=False):
    input_lang, output_lang, pairs = readLangs(lang1, lang2, reverse)
    print("Read %s sentence pairs:" % len(pairs))
    pairs = filterPairs(pairs)
    print("Trimmed to %s sentence pairs:" % len(pairs))
    for pair in pairs:
        input_lang.addSentence(pair[0])
        output_lang.addSentence(pair[1])
    print("Counted words:")
    print(input_lang.name, input_lang.n_words)
    print(output_lang.name, output_lang.n_words)
    return input_lang, output_lang, pairs

input_lang, output_lang, pairs = prepareData('eng', 'fra', True)
print(random.choice(pairs))

#seq2seq model
class EncoderRNN(nn.Module):
    def __init__(self,input_size,hidden_size):
        super(EncoderRNN,self).__init__()
        self.hidden_size = hidden_size
        self.embedding = nn.Embedding(input_size,hidden_size)
        self.gru = nn.GRU(hidden_size,hidden_size)

    def forward(self,input,hidden):
        embedded = self.embedding(input).view(1,1,-1)
        output = embedded
        output,hidden = self.gru(output,hidden)
        return output,hidden

    def initHidden(self):
        result = Variable(torch.zeros(1,1,self.hidden_size))
        return result

class DecoderRNN(nn.Module):
    def __init__(self,hidden_size,output_size):
        super(DecoderRNN,self).__init__()
        self.hidden_size = hidden_size
        self.embedding = nn.Embedding(output_size,hidden_size)
        self.gru = nn.GRU(hidden_size,hidden_size)
        self.out = nn.Linear(hidden_size,output_size)
        self.softmax = nn.LogSoftmax(dim=1)

    def forward(self,input,hidden):
        output = self.embedding(input).view(1,1,-1)
        output = F.relu(output)
        output,hidden = self.gru(output,hidden)
        output = self.softmax(self.out(output[0]))
        return output,hidden

    def initHidden(self):
        result = Variable(torch.zeros(1,1,self.hidden_size))
        return result

#Attention Decoder
class AttnDecoderRNN(nn.Module):
    def __init__(self, hidden_size, output_size, dropout_p=0.1, MAX_LENGTH=max_length):
        super(AttnDecoderRNN, self).__init__()
        self.hidden_size = hidden_size
        self.output_size = output_size
        self.dropout_p = dropout_p
        self.MAX_LENGTH = MAX_LENGTH

        self.embedding = nn.Embedding(self.output_size, self.hidden_size)
        self.attn = nn.Linear(self.hidden_size * 2, self.MAX_LENGTH)
        self.attn_combine = nn.Linear(self.hidden_size * 2, self.hidden_size)
        self.dropout = nn.Dropout(self.dropout_p)
        self.gru = nn.GRU(self.hidden_size, self.hidden_size)
        self.out = nn.Linear(self.hidden_size, self.output_size)

    def forward(self, input, hidden, encoder_outputs):
        embedded = self.embedding(input).view(1,1,-1)
        embedded = self.dropout(embedded)
        attn_weights = F.softmax(self.attn(torch.cat((embedded[0], hidden[0]), 1)), dim=1)
        attn_applied = torch.bmm(attn_weights.unsqueeze(0), encoder_outputs.unsqueeze(0))
        output = torch.cat((embedded[0], attn_applied[0]), 1)
        output = self.attn_combine(output).unsqueeze(0)
        output = F.relu(output)
        output, hidden = self.gru(output, hidden)
        output = F.log_softmax(self.out(output[0]), dim = 1)
        return output, hidden, attn_weights

    def initHidden(self):
        result = Variable(torch.zeros(1,1,self.hidden_size))
        return result

#Training
def indexesFromSentence(lang, sentence):
    return[lang.word2index[word] for word in sentence.split(' ')]

def varibleFromSentence(lang, sentence):
    indexes = indexesFromSentence(lang, sentence)
    indexes.append(eos_token)
    result = Variable(torch.LongTensor(indexes).view(-1,1))
    return result

def variablesFromPair(pair):
    input_variable = varibleFromSentence(input_lang, pair[0])
    target_variable = varibleFromSentence(output_lang, pair[1])
    return (input_variable, target_variable)

# training the model
teacher_forcing_ratio = 0.5

def train(input_variable, target_variable, encoder, decoder, encoder_optimizer, decoder_optimizer, criterion, MAX_LENGTH=max_length):
    encoder_hidden = encoder.initHidden()

    encoder_optimizer.zero_grad()
    decoder_optimizer.zero_grad()

    input_length = input_variable.size()[0]
    target_length = target_variable.size()[1]

    encoder_outputs = Variable(torch.zeros(MAX_LENGTH, encoder.hidden_size))

    loss = 0

    for ei in range(input_length):
        encoder_output, encoder_hidden = encoder(input_variable[ei], encoder_hidden)
        encoder_outputs[ei] = encoder_output[0][0]

    decoder_input = Variable(torch.LongTensor([[sos_token]]))

    decoder_hidden = encoder_hidden
    use_teacher_forcing = True if random.random() < teacher_forcing_ratio else False

    if use_teacher_forcing:
        for di in range(target_length):
            decoder_output, decoder_hidden, decoder_attention = decoder(decoder_input, decoder_hidden, encoder_outputs)
            loss += criterion(decoder_output, target_variable[di])
            decoder_input = target_variable[di]

    else:
        for di in range(target_length):
            decoder_output, decoder_hidden, decoder_attention = decoder(decoder_input, decoder_hidden, encoder_outputs)
            topv, topi = decoder_output.data.topk(1)
            ni = topi[0][0]

            decoder_input = Variable(torch.LongTensor([[ni]]))
            loss += criterion(decoder_output, target_variable[di])
            if ni == eos_token:
                break

    loss.backward()

    encoder_optimizer.step()
    decoder_optimizer.step()
    return loss.data / target_length

import time
import math

def asMinutes(s):
    m = math.floor(s / 60)
    s -= m * 60
    return '%dm %ds' % (m,s)

def timeSince(since, percent):
    now = time.time()
    s = now - since
    es = s / (percent)
    rs = es - s
    return '%s (- %s)' % (asMinutes(s), asMinutes(rs))

def trainIters(encoder, decoder, n_iters, print_every=1000, plot_every=100, learning_rate=0.01):
    start = time.time()
    plot_losses = []
    print_loss_total = 0
    plot_loss_total = 0

    encoder_optimizer = optim.SGD(encoder.parameters(), lr=learning_rate)
    decoder_optimizer = optim.SGD(decoder.parameters(), lr=learning_rate)
    training_pairs = [variablesFromPair(random.choice(pairs)) for i in range(n_iters)]
    criterion = nn.NLLLoss()

    for iter in range(1, n_iters + 1):
        training_pair = training_pairs[iter - 1]
        input_variable = training_pair[0]
        target_variable = training_pair[1]

        loss = train(input_variable, target_variable, encoder,decoder, encoder_optimizer, decoder_optimizer, criterion)
        print_loss_total +=loss
        plot_loss_total +=loss

        if iter % print_every == 0:
            print_loss_avg = print_loss_total / print_every
            print_loss_total = 0
            print('%s (%d %d%%) %.4f' % (timeSince(start, iter / n_iters), iter, iter / n_iters * 100, print_loss_avg))

        if iter % plot_every ==0:
            plot_loss_avg = plot_loss_total / plot_every
            plot_losses.append(plot_loss_avg)
            plot_loss_total = 0
    print('11111111111')
    showPlot(plot_losses)

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

def showPlot(points):
    plt.figure()
    fig, ax = plt.subplots()
    loc = ticker.MultipleLocator(base=0.2)
    ax.yaxis.set_major_locator(loc)
    plt.plot(points)

def evaluate(encoder, decoder, sentence, MAX_LENGTH=max_length):
    input_variable = varibleFromSentence(input_lang, sentence)
    input_length = input_variable.size()[0]
    encoder_hidden = encoder.initHidden()
    encoder_outputs = Variable(torch.zeros(MAX_LENGTH, encoder.hidden_size))

    for ei in range(input_length):
        encoder_output, encoder_hidden = encoder(input_variable[ei], encoder_hidden)
        encoder_outputs[ei] = encoder_outputs[ei] + encoder_output[0][0]
        decoder_input = Variable(torch.LongTensor([[sos_token]]))
        decoder_hidden = encoder_hidden
        decoded_words = []
        decoder_attentions = torch.zeros(MAX_LENGTH, MAX_LENGTH)

    for di in range(MAX_LENGTH):
        decoder_output, decoder_hidden, decoder_attention = decoder(decoder_input, decoder_hidden, encoder_outputs)
        decoder_attentions[di] = decoder_attention.data
        topv,topi = decoder_output.data.topk(1)
        ni = topi.item()
        if ni == eos_token:
            decoded_words.append('<eos>')
            break
        else:
             decoded_words.append(output_lang.index2word[ni])

        decoder_input = Variable(torch.LongTensor([[ni]]))

    return decoded_words, decoder_attentions[:di +1]

def evaluateRandomly(encoder, decoder, n=10):
    for i in range(n):
        pair = random.choice(pairs)
        print('>',pair[0])
        print('=',pair[1])
        output_words, attentions = evaluate(encoder, decoder, pair[0])
        output_sentence = ' '.join(output_words)
        print('<',output_sentence)
        print('')

# hidden_size = 256
hidden_size = 100
encoder1 = EncoderRNN(input_lang.n_words, hidden_size)
attn_decoder1 = AttnDecoderRNN(hidden_size, output_lang.n_words, dropout_p=0.1)

trainIters(encoder1, attn_decoder1, 1000, print_every=100)
output_words, attentions = evaluate(encoder1, attn_decoder1, "je suis trop froid .")
plt.matshow(attentions.numpy())

evaluateRandomly(encoder1, attn_decoder1)

def showAttention(input_sentence, output_words, attentions):
    fig = plt.figure()
    ax = fig.add_subplot(111)
    cax = ax.matshow(attentions.numpy(), cmap='bone')
    fig.colorbar(cax)
    ax.set_xticklabels([''] + input_sentence.split(' ') + ['<eos>'], rotation=90)
    ax.set_yticklabels([''] + output_words)

    ax.xaxis.set_major_locator(ticker.MultipleLocator(1))
    ax.yaxis.set_major_locator(ticker.MultipleLocator(1))

    plt.show()

def evaluateAndShowAttention(input_sentence):
    output_words, attentions = evaluate(encoder1, attn_decoder1, input_sentence)
    print('input=',input_sentence)
    print('output=',' '.join(output_words))
    showAttention(input_sentence, output_words, attentions)

evaluateAndShowAttention("elle a cinq ans de moins que moi .")
# evaluateAndShowAttention("elle est trop petit .")
# evaluateAndShowAttention("je ne crains pas de mourir .")
# evaluateAndShowAttention("c est un jeune directeur plein de talent .")



















































