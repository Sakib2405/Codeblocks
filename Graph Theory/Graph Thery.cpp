#include<stdio.h>
#include<iostream>

using namespace std;

int adj[100][100];
int main(){
int node, edge;

printf("Enter the number of nodes: ");
scanf("%d,&node");

printf(" Enter the number of egde: ");
scanf("%d", &edge);

int n1, n2;
for(int i =0; i<edge; ++i)
{
  scanf("%d %d", &n1, &n2);
   adj[n1][n2]=1;
   adj [n2][n1]=1;
}
for(int i=0; i<node; i++){
    for(int j=0; j<node; ++j){
        printf("%d\t", adj[i][j]);
    }
    printf("\n");
}

}
